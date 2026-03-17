"""Create a FAIR-ready package for the dataset.

This script is dataset-agnostic. It collects the key outputs of the
pipeline for the dataset that owns this file and organises them into
two user-facing layers:

- ``publication/``  - primary files intended for repository upload
	(e.g. standardised CSVs, main EML, compact metadata, RO-Crate).
- ``advanced/``     - additional technical artefacts for advanced
	users (canonical Parquet tables, QA report, manifest, config,
	mappings).

It then assembles these into a versioned directory under ``packages/``
and also creates a ZIP archive that can be uploaded to a repository
(e.g. Dataverse, Zenodo).
"""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List

import yaml

from etl import metadata as etl_metadata


HERE = Path(__file__).resolve()
DATASET_DIR = HERE.parents[1]


def load_yaml(path: Path) -> Dict[str, Any]:
	if not path.exists():
		return {}
	with open(path, "r", encoding="utf-8") as fh:
		return yaml.safe_load(fh) or {}


def prepare_package_dir(label: str | None = None) -> Path:
	cfg = load_yaml(DATASET_DIR / "dataset.yaml")
	dataset_id = (cfg.get("dataset") or {}).get("id", DATASET_DIR.name)

	ts = datetime.now(timezone.utc).strftime("%Y%m%d")
	suffix = label or ts

	packages_dir = DATASET_DIR / "packages"
	packages_dir.mkdir(parents=True, exist_ok=True)

	package_dir = packages_dir / f"{dataset_id}_{suffix}"
	if package_dir.exists():
		shutil.rmtree(package_dir)
	package_dir.mkdir(parents=True, exist_ok=True)
	return package_dir


def copy_if_exists(src: Path, dst: Path) -> None:
	if not src.exists():
		return
	if src.is_dir():
		shutil.copytree(src, dst, dirs_exist_ok=True)
	else:
		dst.parent.mkdir(parents=True, exist_ok=True)
		shutil.copy2(src, dst)


def _build_publication_rocrate(publication_dir: Path) -> None:
	"""Create a RO-Crate descriptor for the publication layer.

	This RO-Crate is intended for repository upload and therefore
	points at the CSV (or similar text) exports under publication/data/
	and key metadata files under publication/metadata/.
	"""

	cfg = load_yaml(DATASET_DIR / "dataset.yaml")
	d = cfg.get("dataset") or {}
	dataset_id = d.get("id", DATASET_DIR.name)
	title = d.get("title", dataset_id)

	# Optional human-authored metadata to enrich the crate.
	human = etl_metadata._load_human_metadata(DATASET_DIR, dataset_id)

	files: List[Dict[str, Any]] = []

	# Data files: everything under publication/data/ (typically CSVs).
	data_root = publication_dir / "data"
	if data_root.exists():
		for p in sorted(data_root.rglob("*")):
			if not p.is_file():
				continue
			rel = p.relative_to(publication_dir)
			files.append(
				{
					"path": str(rel),
					"kind": "data",
					"size_bytes": int(p.stat().st_size),
					"sha256": etl_metadata._sha256_file(p),
				}
			)

	# Metadata files we want to expose alongside the data (e.g. EML, JSON-LD).
	md_root = publication_dir / "metadata"
	if md_root.exists():
		for p in sorted(md_root.rglob("*")):
			if not p.is_file():
				continue
			rel = p.relative_to(publication_dir)
			files.append(
				{
					"path": str(rel),
					"kind": "metadata",
					"size_bytes": int(p.stat().st_size),
					"sha256": etl_metadata._sha256_file(p),
				}
			)

	manifest = {"dataset_id": dataset_id, "files": files}
	crate_path = publication_dir / "ro-crate-metadata.json"

	# Build a minimal but enriched RO-Crate similar to the dataset-level one.
	dataset_entity: Dict[str, Any] = {
		"@id": "./",
		"@type": "Dataset",
		"name": title,
		"identifier": dataset_id,
	}

	desc = human.get("description") or cfg.get("description")
	if desc:
		dataset_entity["description"] = desc

	lic = human.get("license") or (cfg.get("jsonld", {}) or {}).get("license")
	if lic:
		dataset_entity["license"] = lic

	kws = human.get("keywords") or (cfg.get("jsonld", {}) or {}).get("keywords") or []
	if kws:
		dataset_entity["keywords"] = kws

	graph: List[Dict[str, Any]] = []
	person_ids: List[Dict[str, str]] = []
	for idx, contrib in enumerate(human.get("contributors", []) or []):
		name = contrib.get("name")
		if not name:
			continue
		pid = f"#person-{idx+1}"
		person = {
			"@id": pid,
			"@type": "Person",
			"name": name,
		}
		org = contrib.get("affiliation")
		if org:
			person["affiliation"] = org
		graph.append(person)
		person_ids.append({"@id": pid})

	if person_ids:
		dataset_entity["author"] = person_ids

	has_parts: List[Dict[str, str]] = []
	for f in manifest.get("files", []):
		path = f.get("path")
		if not path:
			continue
		size = f.get("size_bytes")
		sha = f.get("sha256")
		kind = f.get("kind")

		file_ent: Dict[str, Any] = {
			"@id": path,
			"@type": "File",
		}
		if size is not None:
			file_ent["contentSize"] = size
		if sha:
			file_ent["sha256"] = sha

		# Provide a simple encodingFormat hint when obvious.
		ext = Path(path).suffix.lower()
		if ext in {".csv", ".tsv"}:
			file_ent["encodingFormat"] = "text/csv"
		elif ext in {".xml", ".eml"}:
			file_ent["encodingFormat"] = "application/xml"
		elif ext == ".json":
			file_ent["encodingFormat"] = "application/json"

		graph.append(file_ent)
		# Only treat data files as hasPart of the dataset; metadata
		# files are implicitly about the dataset and need not be
		# listed in hasPart.
		if kind == "data":
			has_parts.append({"@id": path})

	if has_parts:
		dataset_entity["hasPart"] = has_parts

	meta_ent = {
		"@id": "ro-crate-metadata.json",
		"@type": "CreativeWork",
		"conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
		"about": {"@id": "./"},
		"dateCreated": datetime.now(timezone.utc).isoformat(),
	}

	graph.insert(0, dataset_entity)
	graph.insert(0, meta_ent)

	crate_obj = {
		"@context": "https://w3id.org/ro/crate/1.1/context",
		"@graph": graph,
	}

	crate_path.write_text(
		json.dumps(crate_obj, indent=2),
		encoding="utf-8",
	)


def build_package(label: str | None = None) -> Path:
	package_dir = prepare_package_dir(label=label)

	# Top-level user-facing layers
	publication_dir = package_dir / "publication"
	advanced_dir = package_dir / "advanced"
	publication_dir.mkdir(parents=True, exist_ok=True)
	advanced_dir.mkdir(parents=True, exist_ok=True)

	# ------------------------------------------------------------------
	# Publication layer: primary files for repository upload
	# ------------------------------------------------------------------

	# Data: preferred primary outputs. We treat each subdirectory
	# under exports/ as a named standard (e.g. dwc/, iso19115/,
	# custom_profile/), and mirror it under publication/data/.
	# publication/data/ is therefore the profile-defined set of
	# tables intended for repository deposition; other artefacts
	# live under advanced/.
	exports_root = DATASET_DIR / "exports"
	if exports_root.exists():
		for sub in sorted(exports_root.iterdir()):
			if not sub.is_dir():
				continue
			copy_if_exists(sub, publication_dir / "data" / sub.name)

	# Metadata: choose a single EML (curated > draft > legacy), plus
	# compact machine-readable metadata and ezEML instructions.
	metadata_dir = DATASET_DIR / "metadata"
	pub_md_dir = publication_dir / "metadata"
	if metadata_dir.exists():
		# Preferred EML: curated, else draft, else legacy default.
		for eml_name in ("eml_curated.xml", "eml_draft.xml", "eml.xml"):
			src = metadata_dir / eml_name
			if src.exists():
				copy_if_exists(src, pub_md_dir / eml_name)
				break

		# ezEML instructions, if present
		copy_if_exists(
			metadata_dir / "ezEML_generator_instructions.txt",
			pub_md_dir / "ezEML_generator_instructions.txt",
		)

		# JSON-LD metadata, if present
		copy_if_exists(
			metadata_dir / "metadata.jsonld",
			pub_md_dir / "metadata.jsonld",
		)

	# RO-Crate descriptor inside publication so that the uploaded
	# folder can be treated as a RO-Crate by generic tooling. This
	# publication-layer crate points at the CSV exports and key
	# metadata files shipped under publication/.
	try:
		_build_publication_rocrate(publication_dir)
	except Exception as exc:  # pragma: no cover - defensive
		print("Warning: failed to build publication RO-Crate:", exc)

	# Short human-oriented README explaining what is in this package.
	readme = (
		"This package was created by the LTER-LIFE FAIRification pipeline. It is "
		"designed to be a FAIR, reusable version of the original dataset.\n\n"
		"publication/ contains the main files you would normally upload "
		"to a data repository: standardised data tables (e.g. Darwin Core "
		"CSV files), the primary metadata record (EML), compact machine-"
		"readable metadata (JSON-LD), and a RO-Crate descriptor that "
		"lists these files.\n"
		"advanced/ contains additional technical artefacts for power users: "
		"canonical Parquet tables, the QA report (including DwC checks and "
		"a simple readiness summary), a file manifest, and the configuration "
		"and mappings used to create the data.\n\n"
		"Most depositors will only need the contents of publication/ when "
		"submitting to a repository. Advanced users can consult advanced/ "
		"for provenance, validation results, and fully reproducible re-use.\n"
	)
	# Place the primary README at the package root next to advanced/ and
	# publication/, so users see it immediately when unzipping.
	(package_dir / "README.md").write_text(readme, encoding="utf-8")

	# ------------------------------------------------------------------
	# Advanced layer: canonical data, QA, provenance, config, mappings
	# ------------------------------------------------------------------

	# Canonical Parquet tables
	copy_if_exists(DATASET_DIR / "canonical", advanced_dir / "data" / "canonical")

	# Validation / QA artefacts
	copy_if_exists(
		metadata_dir / "qa_report.json",
		advanced_dir / "validation" / "qa_report.json",
	)

	# Provenance metadata (manifest + minimal dataset metadata)
	copy_if_exists(
		metadata_dir / "manifest.json",
		advanced_dir / "provenance" / "manifest.json",
	)
	copy_if_exists(
		metadata_dir / "dataset_metadata.json",
		advanced_dir / "provenance" / "dataset_metadata.json",
	)

	# Core configuration and standard mappings used to create the data
	copy_if_exists(DATASET_DIR / "dataset.yaml", advanced_dir / "config" / "dataset.yaml")
	copy_if_exists(DATASET_DIR / "mappings", advanced_dir / "config" / "mappings")

	return package_dir


def make_zip(package_dir: Path) -> Path:
	base_name = str(package_dir)
	archive_path = shutil.make_archive(base_name, "zip", root_dir=package_dir)
	return Path(archive_path)


def main(argv: list[str] | None = None) -> None:
	parser = argparse.ArgumentParser(description="Create a FAIR-ready package for this dataset.")
	parser.add_argument(
		"--dataset-dir",
		type=Path,
		default=None,
		help="Path to the dataset directory to package; defaults to the directory owning this file.",
	)
	parser.add_argument(
		"--label",
		help="Optional label for the package directory (defaults to YYYYMMDD)",
	)
	parser.add_argument(
		"--no-zip",
		action="store_true",
		help="If set, do not create a ZIP archive, only the package directory.",
	)
	args = parser.parse_args(argv)

	global DATASET_DIR
	if args.dataset_dir is not None:
		DATASET_DIR = args.dataset_dir.resolve()

	package_dir = build_package(label=args.label)
	print("Created package directory:", package_dir)

	if args.no_zip:
		return

	archive = make_zip(package_dir)
	print("Created ZIP archive:", archive)


if __name__ == "__main__":  # pragma: no cover
	main()

##check what nlbif and dans or gbif use for suggedsting mappings
#myb dont even include this as there is already mapping service out there (DANS)