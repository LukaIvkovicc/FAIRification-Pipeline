
library(shiny)
library(bslib)
library(jsonlite)
library(leaflet)
library(sf)
library(here)
library(DT)
library(readxl)


# ---- Pipeline completion helper (single dataset for now) ----
# Expected package layout (you can later copy/symlink here):
# data-dashboard/fair_packages/walking_forest_2025_latest/
# This represents pipeline completion,formal FAIR score can be evaluated externally and displayed here later.

compute_pipeline_completion <- function(pkg_root) {
  qa_path <- file.path(pkg_root, "advanced", "validation", "qa_report.json")
  if (!file.exists(qa_path)) return(10)

  qa <- tryCatch(jsonlite::fromJSON(qa_path), error = function(e) NULL)
  if (is.null(qa) || is.null(qa$summary)) return(10)

  has_canonical <- isTRUE(qa$summary$has_canonical)
  has_exports <- dir.exists(file.path(pkg_root, "publication", "data"))
  eml_status <- qa$summary$eml_status
  if (is.null(eml_status) || length(eml_status) == 0) eml_status <- "missing"
  has_eml <- eml_status %in% c("draft", "curated", "legacy")

  completion_pct <- 10
  if (has_canonical) completion_pct <- 40
  if (has_exports) completion_pct <- 70
  if (has_eml) completion_pct <- 85
  if (eml_status == "curated") completion_pct <- 100
  completion_pct
}

# ---- THEME ----
app_theme <- bs_theme(
  version = 5,
  bootswatch = "quartz",
  primary = "#3B82F6",
  base_font = font_google("Inter"),
  heading_font = font_google("Inter"),
  bg = "#F4F7FA",
  fg = "#1E293B",
  "body-color" = "#1E293B",
  "secondary-color" = "#475569",
  "card-color" = "#1E293B"
)


# Centralized FAIR steps configuration
FAIR_STEPS <- list(
  prepare = list(
    label = "Describe & prepare",
    icon = "bi-pencil",
    color = "#4C6EF5",
    progress = 20,
    help = "Step 1: Describe the dataset and declare its profile so the pipeline knows what to expect.",
    views = c("Raw Dataset", "Dataset Profile"),
    before = "Raw input",
    after = "Profile-aware dataset",
    transformers = NULL
  ),
  structure = list(
    label = "Structure",
    icon = "bi-table",
    color = "#1C7ED6",
    progress = 40,
    help = "Step 2: Reorganize into canonical tables (events, occurrences, measurements) and add stable IDs.",
    views = c("Before", "After"),
    before = "Flat table",
    after = "Relational structure",
    transformers = c("transform.py")
  ),
  standards = list(
    label = "Standards",
    icon = "bi-diagram-3",
    color = "#7048E8",
    progress = 60,
    help = "Step 3: Align local column names and values with community data standards and ontologies.",
    views = c("Mapping", "JSON-LD"),
    before = "Local labels",
    after = "Standard vocabulary",
    transformers = c("export_standard.py")
  ),
  metadata = list(
    label = "Metadata",
    icon = "bi-journal-text",
    color = "#E67700",
    progress = 80,
    help = "Step 4: Create machine-readable metadata (EML/JSON-LD) describing the dataset and variables.",
    views = c("Metadata files", "Why it matters"),
    before = "Data only",
    after = "Metadata enriched",
    transformers = c("metadata.py")
  ),
  validate = list(
    label = "Validate",
    icon = "bi-patch-check",
    color = "#2F9E44",
    progress = 95,
    help = "Step 5: Run QA checks and package data for distribution.",
    views = c("Package contents", "Readiness"),
    before = "Draft package",
    after = "Verified package",
    transformers = c("validate.py", "package.py")
  ),
  publish = list(
    label = "Publish",
    icon = "bi-upload",
    color = "#1E293B",
    progress = 100,
    help = "Step 6: Deposit package in a repository and mint persistent identifiers.",
    views = c("Record", "Assessment"),
    before = "Local package",
    after = "DOI dataset"
    # Note: This step is outside the current pipeline and focuses on post-FAIRification publication and assessment - no transformers here
  )
)

ui <- page_navbar(
  theme = app_theme,
  title = "LTER-LIFE FAIRifier",
  id = "main_nav",

  header = tags$head(
    tags$link(
      rel = "stylesheet",
      href = "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css"),
      tags$style(HTML("
/* =====================================================
GLOBAL STYLES & VARIABLES
===================================================== */
:root {
  --bs-body-color: #1E293B;
  --bs-heading-color: #0F172A;

  --bs-card-color: #1E293B;
  --bs-card-bg: #FFFFFF;

  --bs-secondary-color: #475569;

  --bs-link-color: #2563EB;
  --bs-link-hover-color: #1D4ED8;
}

/* Page background */
body {
  background: linear-gradient(180deg, #F4F7FA 0%, #E8EEF5 100%) !important;
  color: var(--bs-body-color);
}

/* Headings */
h1,h2,h3,h4,h5,h6 {
  color: var(--bs-heading-color) !important;
}

/* =====================================================
NAVBAR
===================================================== */
.navbar{
  background: linear-gradient(45deg, #134e5e 0%, #71b280 100%) !important;
  padding-top: 0.35rem;
  padding-bottom: 0.35rem;
  min-height: 44px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  box-shadow: 0 1px 0 rgba(0,0,0,0.25);
}

.navbar .navbar-brand{
  color: #F9FAFB !important;
  font-weight: 600;
  letter-spacing: 0.03em;
}

.navbar .nav-link{
  color: rgba(255,255,255,0.75) !important;
  font-weight: 500;
}

.navbar .nav-link.active{
  color: #FFFFFF !important;
  border-bottom: 2px solid rgba(255,255,255,0.6);
}

/* =====================================================
SIDEBAR 
===================================================== */

.sidebar {
  background: linear-gradient(180deg, #F8FAFC 0%, #EEF2F7 100%) !important;
  border-right: 1px solid #E2E8F0;
  padding: 1.4rem 1.2rem;
  box-shadow: 2px 0 12px rgba(15,23,42,0.04);
}

/* Base sidebar text */
.sidebar {
  color: #1E293B !important;
}

/* Muted text */
.sidebar .text-muted,
.sidebar small,
.sidebar .small {
  color: #475569 !important;
  opacity: 1 !important;
}

.sidebar-section-header h4 {
  font-weight: 600;
  margin-bottom: 0.2rem;
}

.sidebar-section-header small {
  display: block;
  font-size: 0.8rem;
  line-height: 1.2;
}

.sidebar-meta-controls {
  margin-top: 0.6rem;
}


/* Checkbox styling */
.sidebar input[type='checkbox'] {
  width: 18px;
  height: 18px;
  accent-color: #3B82F6;
  cursor: pointer;
}

/* Checkbox container */
.sidebar .form-check {
  margin-top: 0.8rem;
  padding: 0.6rem;
  background: #F1F5F9;
  border-radius: 10px;
  border: 1px solid #E2E8F0;
}


/* =====================================================
CARDS
===================================================== */

.card{
  background-color: #FDFEFE !important;
  color: var(--bs-card-color) !important;
  border: 1px solid rgba(15,23,42,0.06);
  border-radius: 16px;
  box-shadow:
    0 1px 2px rgba(15,23,42,0.04),
    0 8px 24px rgba(15,23,42,0.06);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.card:hover{
  transform: translateY(-1px);
  box-shadow:
    0 4px 8px rgba(15,23,42,0.06),
    0 12px 28px rgba(15,23,42,0.08);
}

.card-header{
  background: #F8FAFC !important;
  border-bottom: 1px solid #E2E8F0 !important;
  font-weight: 600;
  color: var(--bs-card-color) !important;
}

.card-body{
  color: var(--bs-card-color) !important;
}

/* =====================================================
NAV TABS (Inside Cards)
===================================================== */
.sidebar .nav-link {
  color: #334155 !important;
  font-weight: 500;
}

.sidebar .nav-link.active {
  color: #1E293B !important;
  font-weight: 600;
  border-left: 3px solid #3B82F6;
  padding-left: 0.75rem;

}

.sidebar .nav-link:hover {
  color: #0F172A !important;
}

/* =====================================================
BUTTONS
===================================================== */
.btn-primary{
  background-color: #2563EB;
  border-color: #2563EB;
  box-shadow: 0 2px 6px rgba(37,99,235,0.35);
}

.btn-primary:hover{
  background-color: #1D4ED8;
  border-color: #1D4ED8;
  box-shadow: 0 4px 10px rgba(37,99,235,0.45);
}

/* FAIR progress bar */
.fair-progress-wrapper{ margin-top: 0.25rem; }
.fair-progress-label{ font-size: 0.8rem; color: #4B5563; margin-top: 0.4rem; }
.progress.fair-progress-track{
  height: 0.5rem;
  background-color: rgba(15, 23, 42, 0.05);
  border-radius: 999px;
}
.progress-bar.fair-progress-bar{
  background: linear-gradient(90deg, #22c55e, #3b82f6);
  border-radius: 999px;
  min-width: 40px;
}

/* =======================================
Step visuals 
========================================= */

.cleaning-compare {
  display: flex;
  gap: 1.2rem;
  align-items: stretch;
  margin-top: 0.8rem;
}

.cleaning-panel {
  flex: 1;
  background-color: #F8FAFC;
  border-radius: 14px;
  padding: 1rem 1.1rem;
  border: 1px solid #E2E8F0;
  box-shadow: 0 2px 8px rgba(15,23,42,0.04);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.cleaning-panel:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(15,23,42,0.06);
}

.cleaning-panel h5 {
  font-size: 0.92rem;
  margin-top: 0;
  margin-bottom: 0.6rem;
  font-weight: 600;
  color: #0F172A;
}

.cleaning-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

.cleaning-table th,
.cleaning-table td {
  border-bottom: 1px solid #E2E8F0;
  padding: 0.35rem 0.4rem;
}

.cleaning-table th {
  font-weight: 600;
  color: #334155;
}

/* ==============================
FAIR Timeline 
============================== */

.sidebar .shiny-input-radiogroup {
  position: relative;
  margin-top: 0.4rem !important;
}

/* Hide native radios */
.sidebar .shiny-input-radiogroup input[type='radio'] {
  position: absolute;
  opacity: 0;
}

/* Step labels */
.sidebar .shiny-input-radiogroup label {
  position: relative;
  display: block;
  padding: 0.75rem 1rem 0.75rem 3rem;
  margin-bottom: 0.9rem;
  font-weight: 500;
  font-size: 0.96rem;
  color: #64748B !important;
  border-radius: 14px;
  transition: all 0.22s cubic-bezier(.4,0,.2,1);
  cursor: pointer;
}

/* Step circle */
.sidebar .shiny-input-radiogroup label::before {
  content: '';
  position: absolute;
  left: 18px;
  top: 50%;
  transform: translateY(-50%);
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #CBD5E1;
  transition: all 0.22s ease;
}

/* Connector line */
.sidebar .shiny-input-radiogroup label:not(:last-of-type)::after {
  content: '';
  position: absolute;
  left: 24px;
  top: calc(100% - 6px);
  height: 24px;
  width: 2px;
  background: #E2E8F0;
}

/* -----------------------------------
HOVER STATE 
----------------------------------- */

.sidebar .shiny-input-radiogroup label:hover {
  background: linear-gradient(90deg, #F1F5F9 0%, #FFFFFF 100%);
  color: #0F172A !important;
  transform:translateY(-3px);
  box-shadow:0 6px 16px rgba(0,0,0,0.08);
  
}

/* Hover circle */
.sidebar .shiny-input-radiogroup label:hover::before {
  background: #94A3B8;
}

/* -----------------------------------
ACTIVE STATE 
----------------------------------- */

.sidebar .shiny-input-radiogroup label.active,
.sidebar .shiny-input-radiogroup label[aria-checked='true'] {
  background: linear-gradient(90deg, #E0F2FE 0%, #F8FBFF 100%);
  font-weight: 600;
  color: #0F172A !important;
  box-shadow: 0 8px 22px rgba(59,130,246,0.18);
  transform: translateX(6px);
}

/* Active circle */
.sidebar .shiny-input-radiogroup label.active::before,
.sidebar .shiny-input-radiogroup label[aria-checked='true']::before {
  background: #3B82F6;
  box-shadow: 0 0 0 5px rgba(59,130,246,0.2);
}

/* Last step styling */
.sidebar .shiny-input-radiogroup label:last-of-type {
  margin-top: 1.4rem;
  padding-top: 1.1rem;
  border-top: 1px solid #E2E8F0;
  font-style: italic;
  color: #6B7280 !important;
}


/* =====================================================
   FIX: Remove Empty Shiny Radio Label Container
   ===================================================== */

/* Remove the automatically generated empty label above radioButtons */
#fair_step-label {
  display: none !important;
  margin: 0 !important;
  padding: 0 !important;
  height: 0 !important;
}

/* Remove extra spacing from the radio group wrapper */
#fair_step {
  margin-top: 0 !important;
}

/* Remove Bootstrap bottom margin from label container */
.sidebar .form-group {
  margin-bottom: 0.4rem !important;
}

/* Tighten radio group spacing */
.sidebar .shiny-input-radiogroup {
  margin-top: 0.2rem !important;
  padding-top: 0 !important;
}
 /* YAML viewer containers */
  #dataset_config_box, #dataset_profile_box {
      background: #027063;
      border: 1px solid #3B82F6;
      border-radius: 12px;
      padding: 1rem;
      max-height: 450px;
      overflow: auto;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
    }
   #metadata_draft_box {
      background: #027063;
      border: 1px solid #3B82F6;
      border-radius: 12px;
      padding: 1rem;
      max-height: 450px;
      overflow: auto;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
    }

   #mapping_box {
      background: #027063;
      border: 1px solid #3B82F6;
      border-radius: 12px;
      padding: 1rem;
      max-height: 650px;
      overflow: auto;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
    }
    
    #validation_report_box {
      background: #027063;
      border: 1px solid #3B82F6;
      border-radius: 12px;
      padding: 1rem;
      max-height: 650px;
      overflow: auto;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
    }

 /* Force readable text inside verbatimTextOutput (<pre>) */
   #dataset_config_yaml, #dataset_profile_yaml, #mapping_yaml,
    #metadata_draft_preview, #validation_report_preview {
      color: #E5E7EB !important;
      background: transparent !important;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace !important;
      font-size: 0.90rem;
      line-height: 1.55;
      white-space: pre;
      margin: 0;
    }

/* =====================================================
   TABLE (DT) COLOR OVERRIDES — neutralize quartz purple
   Inserted to ensure DataTables use readable, light backgrounds
===================================================== */
.dataTables_wrapper, table.dataTable, .dataTable {
  background: transparent !important;
  color: #0F172A !important;
}
table.dataTable thead th {
  background: #F8FAFC !important;
  color: #334155 !important;
  border-bottom: 1px solid #E2E8F0 !important;
}
table.dataTable tbody td {
  background: transparent !important;
  color: #0F172A !important;
  border-bottom: 1px solid #E9EEF5 !important;
}
table.dataTable tbody tr:hover {
  background: #F1F5F9 !important;
}
.dataTables_wrapper .dataTables_paginate .paginate_button {
  background: transparent !important;
  border: 1px solid rgba(15,23,42,0.06) !important;
  color: #374151 !important;
}
.dataTables_wrapper .dataTables_info, .dataTables_wrapper .dataTables_length {
  color: #475569 !important;
}
/* Ensure DT's built-in classes used by Shiny/BS do not force purple backgrounds */
.dt-buttons .btn, .dataTables_wrapper .btn {
  background: transparent !important;
  border: 1px solid rgba(15,23,42,0.06) !important;
  color: #334155 !important;
}

/* STEP 2 – Before/After visuals */

.step-images .figure {
  margin-bottom: 0;
}

.step-images img {
  width: 100%;
  max-height: 520px;   /* makes them visually larger */
  object-fit: contain; /* preserves whole screenshot */
  border-radius: 8px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.08);
  background: #ffffff; /* removes transparency weirdness */
  padding: 6px;        /* subtle framing */
}

.step-images figcaption {
  font-size: 0.85rem;
  color: #6b7280;
  margin-top: 0.4rem;
}

/* Slightly larger on big screens */
@media (min-width: 1400px) {
  .step-images img {
    max-height: 620px;
  }

  "))
  ),

  # =========================
  # =========================
  # INTRODUCTION
  # =========================
    nav_panel(
    "Introduction",
      layout_sidebar(
        sidebar = sidebar(
        h4("Navigation"),
        p("Start here to understand the app, the FAIR concept, and the journey you'll follow."),
        tags$hr(),
        tags$small(class = "text-muted",
                   "Tip: Each section below answers a key question to help you onboard quickly.")
      ),
        card(
        card_body(
          h2("Welcome to the LTER-LIFE FAIRifier"),
          p("Ecological research increasingly depends on datasets that can be discovered, interpreted, integrated, and reused across projects, disciplines, and time.
          Yet many valuable datasets remain difficult to integrate beyond their original study context — usually because of structural and semantic inconsistencies rather than scientific limitations.
          The FAIR principles provide a framework for addressing these challenges."),
          p("FAIRfier traces how a real ecological monitoring dataset is transformed through an automated FAIRification pipeline — from raw field observations to a structured, standards-aligned dataset prepared as a reusable research object."),
          hr(),
          div(
  style = "display:flex; align-items:center; justify-content:space-between;",
  h2("What is FAIR?", style="margin-bottom:0;"),
 actionLink(
  "show_fair_info",
  label = "Learn more about FAIR",
  icon = icon("info-circle"),
  style = "font-size:0.95em; color:#5D6D78; text-decoration:none;"
)
),
          p("FAIR describes principles that make research data Findable, Accessible, Interoperable, and Reusable. These principles ensure that datasets can be discovered, interpreted, integrated, and reused by both humans and machines."),
          conditionalPanel(
  condition = "input.show_fair_info % 2 == 1",
  div(
    style = "
      background:#f8fafc;
      border-left:4px solid #3B82F6;
      border-radius:6px;
      padding:1rem 1.2rem;
      margin-top:0.8rem;
      margin-bottom:1rem;
    ",

    tags$strong("About the FAIR Principles"),

    p(
      "The FAIR Guiding Principles were formally introduced by Wilkinson et al. (2016) in ",
      tags$em("Scientific Data"),
      " to support machine-actionable research ecosystems."
    ),

    p("Importantly, FAIR does not necessarily mean open. Data can be FAIR while remaining access-restricted, provided that access conditions are clearly described and machine-readable."),

    tags$ul(
      tags$li("Published in ", tags$em("Scientific Data"), " (2016)"),
      tags$li("Designed to enable machine-actionable research ecosystems"),
      tags$li("Adopted across international research infrastructures and funding bodies")
    ),

    tags$p(
      tags$a(
        "Read the original publication (Wilkinson et al., 2016)",
        href = "https://doi.org/10.1038/sdata.2016.18",
        target = "_blank"
      )
    )
  )
),
          p("These dimensions are not achieved all at once. They emerge progressively as data becomes structured, standardized, documented, and validated through a transparent workflow."),
          p(class = "text-muted", "FAIR is cumulative, not binary — each workflow stage strengthens different dimensions."),
          div(style = "display: flex; flex-direction: column; align-items: center; margin: 1.5rem 0;",
            img(src = "Fair-graphic-v2.png",alt = "FAIR principles graphic",
              style = "max-width: 640px; width: 100%; height: auto; margin-bottom: 0.7rem; box-shadow: 0 2px 12px rgba(0,0,0,0.07);"),
            tags$small(class = "text-muted",style = "font-size:1.02em;","Conceptual overview of the FAIR principles. Source: ",
                tags$a("CESSDA Data Archiving Guide, Chapter 5",href = "https://dag.cessda.eu/Chapter-5",target = "_blank"),
                  ".")),
          hr(),
h2("Why FAIRification Matters"),

p("FAIR ecological datasets support collaboration, long-term reuse, and integration across multiple research domains.
  They allow independent studies to become interoperable components of shared research infrastructures and knowledge systems."),

p("When datasets are structured, standardized, and documented consistently, they can support shared research infrastructures, 
  comparative analyses, policy decisions, and future modeling efforts — including ecosystem-scale simulations and Digital Twins."),

# Image container
div(
  style = "display: flex; flex-direction: column; align-items: center; margin: 1.5rem 0;",
  
  img(
    src = "FAIRdataprinciples_foster.png",
    alt = "Illustration of FAIR data principles in practice",
    style = "max-width: 900px; width: 100%; height: auto; margin-bottom: 0.5rem;"
  ),
  
  tags$small(
    class = "text-muted",
    style = "font-size:1.02em;",
    "Illustration of FAIR data principles in practice. Source: ",
    tags$a(
      "OpenAIRE – What is FAIR Data?",
      href = "https://www.openaire.eu/what-is-fair-data",
      target = "_blank"
    ),
    "."
  )
),
hr(),
h2("Meet the Walking Forest Dataset"),
          
          p("This walkthrough is grounded in the Walking Forest dataset — an ecological monitoring study of oak regeneration in the Millingerwaard floodplain, the Netherlands.
          Like many research datasets, it was originally structured to support a specific study and analytical workflow. 
          In that context, spreadsheets and heterogeneous files are practical and effective tools."),

          p("However, when datasets are shared beyond their original project, certain structural and semantic elements
           that were previously implicit may benefit from clarification or formalization.
           For example:",
            tags$ul(
              tags$li("Context, entities, and measurements may be recorded within the same table"),
              tags$li("Identifiers may function locally rather than globally"),
              tags$li("Metadata may exist in documents rather than machine-readable formats"),
              tags$li("Local labels without standard vocabularies"),
              tags$li("Terminology may reflect domain and local language rather than shared vocabularies")
            )
          ),
          p("These characteristics are common in research environments and do not reflect scientific limitations — they simply reflect
           the dataset’s original design purpose."),
          p("FAIRification does not change the ecological content of the dataset — it changes how the dataset can be understood, validated, and reused beyond its original context."),
          div(style = "display: flex; flex-direction: column; align-items: center; margin: 1.2rem 0;",
          img(
            src = "walking-forest-millingerwaard.jpg",
            alt = "Millingerwaard floodplain, Netherlands",
            style = "max-width: 700px; width: 100%; height: auto; border-radius: 10px; margin-bottom: 0.5rem; box-shadow: 0 2px 12px rgba(0,0,0,0.08);"),
            tags$small(
  class = "text-muted",
  style = "font-size:1.02em;",
  "Millingerwaard floodplain, Netherlands — field site context for the Walking Forest dataset. ",
  "Photo: Luuk Donderwinkel/K3. Source: ",
  tags$a(
    "European Commission Environment (2024)",
    href = "https://environment.ec.europa.eu/news/transformation-millingerwaard-intensive-agriculture-and-clay-extraction-natural-flood-protection-2024-03-14_en",
    target = "_blank"
  ),
  "."
)),
                div(style = "margin-top:1rem;",
                leafletOutput("intro_millingerwaard_map", height = "260px")
                ),
                tags$small(
                  class = "text-muted",
                  style = "display:block; text-align:center; margin-top:0.3rem; font-size:0.98em;",
                  "Map: Millingerwaard field site location (OpenStreetMap contributors)."),
                  hr(),  
                  h2("The FAIRification Journey"),
          p("As you explore the FAIRifier, you'll see how Walking Forest evolves through six transformation stages — from messy raw files to a FAIR-ready research object."),
          p(
           style = "color:#475569; font-size:1.01em; margin-bottom:0.7rem;",
             "In practice, data preparation, standardization, and metadata development evolve iteratively and often in parallel.
              The FAIRification pipeline implemented here automates these transformations into a coherent, reproducible workflow." 
          ),
          p("Although this walkthrough focuses on a biodiversity monitoring dataset, the FAIRification pipeline is profile-driven and extensible to multiple ecological dataset types and standards."),
          hr(),
      div(style = "display: flex; flex-direction: column; align-items: center; margin: 1.2rem 0;",
            img( src = "app-fair-workflow_new.png", alt = "FAIRification pipeline diagram",style = "max-width: 950px;
             width: 100%; height: auto; border-radius: 10px; margin-bottom: 0.5rem; box-shadow: 0 2px 12px rgba(0,0,0,0.08);"
        ),
           tags$small( class = "text-muted",style = "font-size:1.02em;",
    "FAIRification pipeline: from raw data to FAIR-ready research object.")),
          p("Each step improves structure, semantics, or documentation — gradually transforming raw data into a discoverable, interpretable, and reusable dataset."),
          hr(),
          h2("Ready to Explore?"),
          p("You are now ready to explore how each FAIRification step transforms the dataset in practice."),
      div(
          class = "you-are-here",
          span(class = "bi bi-arrow-right-circle"),
            actionButton(
              inputId = "go_to_fair_story",
              label = "Open the FAIRification story to begin your journey.",
              class = "btn-outline-primary",
              style = "margin-left:0.7em; font-weight:500; border-radius:999px; padding:0.18rem 0.9rem; font-size:1em; background: #f3f6fb; border: 1.5px solid #3B82F6; color: #174ea6; box-shadow: none;"
              )
            )
         )
       )
    )
 ),
# =========================
# FAIRIFICATION STORY
# =========================
    nav_panel(
    "FAIRification story",
      layout_sidebar(
        sidebar = sidebar(

      # ---- Section header ----
        div(
        class = "sidebar-section-header",
        h4("FAIRification journey"),
        tags$small(
          class = "text-muted",
          "Six-step transformation from raw dataset to FAIR ready (pre-publication)"
        )
      ),

      tags$hr(style = "margin: 0.8rem 0 1rem 0;"),

      # ---- FAIR Steps Timeline ----
        div(
        style = "margin-bottom: 0.5rem;",
        radioButtons(
          inputId = "fair_step",
          label = NULL,  # IMPORTANT: remove empty label for accessibility
          choices = setNames(
            c("prepare", "structure", "standards", "metadata", "validate", "publish"),
            c(
              "1. Prepare (profile) data",
              "2. Structure for reuse",
              "3. Apply standards & semantics",
              "4. Create FAIR metadata",
              "5. Validate & package",
              "6. Publish & assess FAIRness (Beyond pipeline)"
            )
          ),
          selected = "prepare"
        )
      ),

      # ---- Step Counter ----
      div(
        style = "margin-top: 1rem;",
        uiOutput("fair_step_counter")
      ),

      tags$hr(),

      # ---- Pipeline Status ----
      h5("FAIR journey & pipeline status"),
      uiOutput("fair_progress")
    ),

    # =========================
    # MAIN CONTENT CARD
    # =========================
      card(
      card_header("FAIRification walkthrough"),
      uiOutput("fair_timeline"),
      uiOutput("fair_step_card_body")
    )
  )
),

  # =========================
  # FAIR TOOLKIT
  # =========================
    nav_panel(
    "FAIR toolkit",
        layout_sidebar(
         sidebar = sidebar(
        h4("Your dataset"),
        fileInput("user_csv", "Upload CSV", accept = c(".csv")),
        textInput("pkg_path", "Local package path (optional)", placeholder = "path/to/fair_package"),
        actionButton("load_pkg", "Load package QA"),
        selectInput(
          "user_dataset_type",
          "Dataset type (for demo)",
          choices = c("Plot-based ecology", "Soil cores", "Hydrology time series", "Other"),
          selected = "Plot-based ecology"
        ),
        actionButton("analyze_user_dataset", "Analyze FAIR gaps")
      ),
        card(
          card_header("How would YOU FAIRify?"),
          card_body(
          p("This is a sandbox: upload a CSV file and see simple feedback about FAIR gaps."),
          p("In v1, keep this lightweight and illustrative, not a full generic FAIRifier."),
          hr(),
          h4("Detected issues (mocked for now)"),
            tableOutput("user_fair_issues"),
            hr(),
            h4("Uploaded CSV preview & diagnostics"),
            uiOutput("user_csv_preview_ui"),
            hr(),
            h4("Package explorer (optional)") ,
            uiOutput("pkg_files_ui"),
            uiOutput("pkg_preview_ui"),
            hr(),
            h4("Dataset simulator (preview transformations)"),
            selectInput("sim_state", "Simulator state:",
                        choices = c("Raw", "Cleaned", "Structured", "FAIR-ready"),
                        selected = "Raw"),
          div(style = "display:flex; gap:0.5rem; align-items:center; margin-bottom:0.5rem;",
                actionButton("sim_prev", "◀ Prev", `aria-label` = "Previous simulation state"),
                actionButton("sim_next", "Next ▶", `aria-label` = "Next simulation state"),
                tags$span(style = "color:#6B7280; margin-left:0.6rem;", "Preview small sample rows for each state.")),
            tableOutput("sim_table"),
            uiOutput("sim_state_desc")
        )
      )
    )
  ),

  # =========================
  # VELUWE FAIR VIEW
  # =========================
  nav_panel(
    "Veluwe FAIR view",
      layout_sidebar(
      sidebar = sidebar(
        h4("Veluwe ecosystem"),
        p("Read-only, curated indicators from FAIR or FAIR-ish datasets: air, soil, hydrology, biodiversity."),
        p("Goal: show how FAIR enables integration across themes, not to build a live monitoring tool."),
        p("This view represents what becomes possible once multiple datasets are FAIR-ready and interoperable."),
        hr(),
        p(class = "text-muted",
          "The map and indicators are illustrative, but reflect how FAIR-ready packages can power integrated views.")
      ),
      card(
        card_header("Veluwe in FAIR data"),
        card_body(
          fluidRow(
            column(
              6,
              leafletOutput("veluwe_map", height = 420)
            ),
            column(
              6,
              tabsetPanel(
                id = "veluwe_tab",
                tabPanel("Air", uiOutput("veluwe_air")),
                tabPanel("Soil", uiOutput("veluwe_soil")),
                tabPanel("Hydrology", uiOutput("veluwe_hydro")),
                tabPanel("Biodiversity", uiOutput("veluwe_bio"))
              )
            )
          )
        )
      )
    )
  ),

  # =========================
  # ABOUT & METHODS
  # =========================
  nav_panel(
    "About & methods",
      layout_sidebar(
      sidebar = sidebar(
        h4("Documentation"),
        p("Describe data sources, ETL pipeline, standards, and limitations."),
        p("Link to the lter-life-labs data-automation repository and relevant publications.")
      ),
      card(
        card_header("Methods & FAIR principles"),
        card_body(
          h3("Pipelines and standards"),
          div(
            style = "text-align: right; margin-top: 0.5rem;",
            actionLink("show_dev_drawer",
                       label = tagList(
                        icon("terminal"),
                        tags$span("Developer: pipeline & package", style = "color: #64748B; font-size: 0.98em; margin-left: 0.3em;")
                ),
                style = "font-size: 1.05em; color: #6B7280; vertical-align: middle;"
            )
              ),
          tags$ul(
            tags$li("Python ETL pipeline: ingest → transform → export_standard → metadata → validate → package"),
            tags$li("Data standards: Darwin Core, EML, JSON-LD, RO-Crate"),
            tags$li("Identifiers and ontologies used (e.g. ENVO, units)"))       
          ),
          hr(),
          h3("Reproducibility"),
          p("Explain how the FAIR package is created (e.g. make run DATASET=datasets/walking_forest LABEL=latest)."),
          p("Clarify what is prototype/demo and what is production-ready."),
          hr(),
          h3("Limitations"),
          p("This application demonstrates FAIRification concepts and workflows. It does not compute formal FAIR scores.")
        )
      )
    ),
    # Starting the new page from top always
    tags$script(HTML(
      "Shiny.addCustomMessageHandler('scrollTop', function(msg) {\n",
      "  var el = document.getElementById('fair_step_card_body');\n",
      "  if (!el) { window.scrollTo({top:0, behavior:'auto'}); return; }\n",
      "  function findScrollable(node) {\n",
      "    while (node) {\n",
      "      var style = window.getComputedStyle(node);\n",
      "      if (style.overflowY === 'auto' || style.overflowY === 'scroll') return node;\n",
      "      node = node.parentElement;\n",
      "    }\n",
      "    return null;\n",
      "  }\n",
      "  var sc = findScrollable(el);\n",
      "  if (sc) sc.scrollTop = 0; else window.scrollTo({top:0, behavior:'auto'});\n",
      "});\n",
      "Shiny.addCustomMessageHandler('scrollToElement', function(msg) { var target=document.querySelector(msg.selector); if (!target) return; var sc=findScrollable(target); if (sc) sc.scrollTop = target.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop; else target.scrollIntoView({behavior:'smooth', block:'start'}); });"
    )))
    

#==========================================================================================
## FUNCTIONALITY: Server logic for interactive elements, maps, and dynamic content ##
#==========================================================================================
  server <- function(input, output, session) {
      # Jump to FAIRification story tab when button is clicked (for bslib::page_navbar)
      observeEvent(input$go_to_fair_story, {
        updateNavbarPage(session, "main_nav", selected = "FAIRification story")
      })
    output$intro_millingerwaard_map <- renderLeaflet({
      cat("MAP RENDER START\n")
      leaflet() %>%
        addTiles() %>%
        setView(lng = 6.022, lat = 51.872, zoom = 13) %>%
        addMarkers(
          lng = 6.022, lat = 51.872,
          popup = "Millingerwaard floodplain"
        )
    })

    # Force redraw when Introduction tab is shown (robust for navbarPage)
    observeEvent(input$main_nav, {
      if (input$main_nav == "Introduction") {
        leafletProxy("intro_millingerwaard_map") %>%
          clearMarkers() %>%
          addMarkers(
            lng = 6.022, lat = 51.872,
            popup = "Millingerwaard floodplain"
          )
      }
    })
    output$pipeline_action <- renderText({
      step <- input$fair_step
      if (is.null(step) || !(step %in% names(FAIR_STEPS))) return("")
      FAIR_STEPS[[step]]$help
    })
  # Introduction tab: horizontal journey diagram (static, always visible)
      output$intro_journey_diagram <- renderUI({
      steps <- names(FAIR_STEPS)
      labels <- vapply(FAIR_STEPS, function(x) x$label, character(1))
      icons <- vapply(FAIR_STEPS, function(x) x$icon, character(1))
      div(
        class = "fair-journey-diagram",
        style = "margin-bottom:0.2rem; align-items:center; justify-content:center; display:flex; gap:0.5rem; position:relative;",
        # horizontal line connector
        tags$div(style="position:absolute;left:2.5%;right:2.5%;top:50%;height:3px;background:linear-gradient(90deg,#e0e7ef 0,#b6c6e2 100%);z-index:0;"),
        lapply(seq_along(steps), function(i) {
          div(
            class = paste0("fair-journey-step"),
            style = "background:#fff;z-index:1;display:flex;align-items:center;gap:0.3rem;padding:0.18rem 0.7rem;border-radius:999px;border:1.5px solid #e5e7eb;box-shadow:0 1px 4px #e5e7eb;",
            span(class = paste0("fair-journey-icon bi ", icons[i]), style="font-size:1.15em;"),
            span(class = "fair-journey-label", style="font-size:1em;font-weight:500;", labels[i]),
            if (i < length(steps)) span(class = "fair-journey-arrow bi bi-arrow-right", style="margin:0 0.2em;color:#b6c6e2;font-size:1.1em;")
          )
        })
      )
    })
  # Initialize package-related reactive values early to avoid timing/timing-order issues
  pkg_file_list <- reactiveVal(NULL)
  pkg_preview <- reactiveVal(NULL)
  pkg_completion <- reactiveVal(NULL)
  # derive progress values from FAIR_STEPS config (declare early to avoid forward reference)
  fair_journey_progress <- vapply(FAIR_STEPS, function(x) x$progress, numeric(1))
  # Dataset transformation summary (user-centric) — use FAIR_STEPS summary
  output$dataset_change_summary <- renderText({
    step <- input$fair_step
    if (is.null(step) || !(step %in% names(FAIR_STEPS))) return("")
    summ <- FAIR_STEPS[[step]]$help
    summ
  })

    # Phase 1: timeline bar (compact) above the journey diagram
    output$fair_timeline <- renderUI({
      steps <- names(fair_journey_progress)
      active <- match(input$fair_step, steps)
      # Render compact dots without visible numbers; keep titles/aria for accessibility
      div(class = "timeline-row",
          lapply(seq_along(steps), function(i) {
            div(
              class = paste("timeline-dot", if (i <= active) "active" else ""),
              title = steps[i],
              `aria-label` = steps[i],
              tags$span(class = "visually-hidden", steps[i])
            )
          })
      )
    })

  # Phase 1: dataset transform panel (simple paired boxes per step) — drive from FAIR_STEPS
  output$dataset_transform_panel <- renderUI({
    step <- input$fair_step
    if (is.null(step) || !(step %in% names(FAIR_STEPS))) return(NULL)
    fs <- FAIR_STEPS[[step]]
    tagList(
      div(class = "transform-row",
          div(class = "transform-box before", fs$before),
          span(class = "transform-arrow", "→"),
          div(class = "transform-box after", fs$after)
      ),
      if (!is.null(fs$transformers) && length(fs$transformers) > 0) {
        div(style = "margin-top:0.5rem;",
            strong("Transformers: "),
            paste(fs$transformers, collapse = " • ")
        )
      }
    )
  })
  # PILLAR 1: Journey header summary
  output$fair_stage_summary <- renderText({
    switch(input$fair_step,
      prepare  = "Raw dataset → prepared foundation",
      structure = "Prepared data → structured tables",
      standards = "Structured data → interoperable semantics",
      metadata = "Data → discoverable research object",
      validate = "Package → FAIR-ready bundle",
      publish = "Bundle → published dataset"
    )
  })

  # System 3: Interactive schema mini-diagram for 'structure' step
  schema_selected <- reactiveVal(NULL)

  observeEvent(input$schema_event, { schema_selected("event") })
  observeEvent(input$schema_occurrence, { schema_selected("occurrence") })
  observeEvent(input$schema_measurement, { schema_selected("measurement") })

  # Reset selection when leaving structure step
  observeEvent(input$fair_step, {
    if (input$fair_step != "structure") schema_selected(NULL)
    else if (is.null(schema_selected())) schema_selected("event")
  })

  # Scroll to top when user navigates between FAIR steps
  observeEvent(input$fair_step, {
    session$sendCustomMessage('scrollTop', list())
  })

  output$schema_diagram_ui <- renderUI({
    # only render in structure step
    req(input$fair_step == "structure")
    sel <- schema_selected()
    div(class = "schema-diagram", style = "margin-top:0.8rem;",
        actionLink("schema_event", div(class = paste("schema-box schema-click", ifelse(sel=="event","active","")), "Event")),
        span(class = "schema-arrow", "→"),
        actionLink("schema_occurrence", div(class = paste("schema-box schema-click", ifelse(sel=="occurrence","active","")), "Occurrence")),
        span(class = "schema-arrow", "→"),
        actionLink("schema_measurement", div(class = paste("schema-box schema-click", ifelse(sel=="measurement","active","")), "Measurement"))
    )
  })

  output$schema_highlight_ui <- renderUI({
    step <- input$fair_step

    if (is.null(step) || !(step %in% names(FAIR_STEPS))) return(NULL)
    fs <- FAIR_STEPS[[step]]
    tagList(
      p(fs$help),
      if (!is.null(fs$views)) tags$small(class = "text-muted", paste("Views:", paste(fs$views, collapse = " • ")))
    )
  })
 ## PILLAR 2: Step identity color wrapper for card body | FAIRification Story: dynamic content per step | ##
  output$fair_step_card_body <- renderUI({
    step_class <- paste0("step-", input$fair_step)
    border_col <- if (!is.null(input$fair_step) && input$fair_step %in% names(FAIR_STEPS)) FAIR_STEPS[[input$fair_step]]$color else "#CBD5E1"
    if (identical(input$fair_step, "prepare")) {
      div(
        class = step_class,
        style = paste0("border-left: 5px solid ", border_col, "; padding-left: 1.1rem;"),
h3("Step 1 — Prepare your dataset and choose a profile"),
tags$small(
  style="color:#64748B;font-size:1.01em;",
  "From raw files to a declared foundation"
),
tags$hr(style="margin:0.7rem 0 1.1rem 0;"),

p("Before any FAIR transformation can begin, the pipeline must understand what your dataset represents and how it should be interpreted."),

p("In this step, you enable FAIRification by preparing your raw data, creating a dataset configuration file, and declaring the dataset profile that applies."),
hr(),

h4("Organize your dataset on your computer"),

p("Before using the FAIRifier, organize your dataset as a small folder on your computer. 
The pipeline reads datasets directly from folders rather than uploading files."),

tags$pre(
"my_dataset/
│
├── raw/
│   └── walking_forest.xlsx
│
└── dataset.yaml"
),

p("This dataset folder can be created anywhere, for example:"),

tags$ul(
  tags$li("Documents or project folders"),
  tags$li("Laboratory shared storage"),
  tags$li("External drives"),
  tags$li("Institutional research servers")
),

div(
  style="margin-top:0.7rem;background:#f8fafc;padding:0.7rem;border-radius:8px;border:1px solid #e2e8f0;",
  tags$em(
    "FAIRifier reads your dataset folder without modifying original files. 
    Your raw data always remains unchanged."
  )
),

hr(),

h4("Prepare the data"),

p("Inside your dataset directory, create a folder named ",
  tags$code("raw/"),
  " and place your original data files inside."
),

tags$ol(
  tags$li("Open your dataset folder."),
  tags$li("Create a new folder named ", tags$code("raw"), "."),
  tags$li("Move your original Excel, CSV, or sensor export files into this folder.")
),

hr(),

h4("Create a dataset configuration file"),

p("Create a file named ",
  tags$code("dataset.yaml"),
  " in your dataset folder. This file links your raw data to a dataset profile and tells the pipeline how your files should be interpreted."
),

p("A minimal configuration looks like:"),

tags$pre(
"dataset:
  id: my_dataset
  profile: ecology
  raw_folder: raw/"
),

tags$ul(
  tags$li(strong("id"), " — a unique identifier for your dataset"),
  tags$li(strong("profile"), " — the structural template to apply"),
  tags$li(strong("raw_folder"), " — location of your original files")
),

p("Additional options (e.g. sheet selection, column renaming, file-specific settings) can be added when needed, but this minimal structure is sufficient to begin."),

div(
  style="margin-top:0.7rem;background:#ecfeff;padding:0.7rem;border-radius:8px;border:1px solid #67e8f9;",
  tags$strong("Tip: "),
  "The dataset identifier should remain stable across the FAIRification workflow."
),

hr(),

h4("Declare the dataset profile"),

p("The dataset profile defines the structural components and standards expected for your dataset type (e.g. ecological monitoring, species observations, environmental measurements)."),

p("The profile is declared inside ",
  tags$code("dataset.yaml"),
  " using the ",
  tags$code("profile:"),
  " field."
),

p("In this walkthrough, the Walking Forest dataset uses the ",
  tags$code("ecology"),
  " profile. The FAIRification pipeline is profile-driven and extensible to other dataset types."),

hr(),

h4("What happens in this step"),

tags$ul(
  tags$li("The pipeline loads your raw files"),
  tags$li("Reads dataset.yaml"),
  tags$li("Validates alignment with the selected profile")
),

p("No structural transformations occur yet. This step establishes a shared interpretation between your dataset and the pipeline."),

hr(),

h4("What changes"),

p(strong("Raw dataset → Profile-aware dataset")),

tags$ul(
  tags$li("The dataset is formally declared"),
  tags$li("The pipeline can interpret its structure"),
  tags$li("Ready for transformation in Step 2 (structure) and beyond")
),

hr(),

h4("Views"),
p("Inspect the raw dataset, configuration file, and selected profile below."),

  tabsetPanel(
  id = "fair_step1_views",

  # -------------------------
  # RAW DATASET
  # -------------------------
  tabPanel(
    "Raw Dataset",

    div(style="margin-bottom:0.6rem;",
        selectInput(
          "raw_sheet_select",
          "Select sheet:",
          choices = if (file.exists(raw_xlsx_path)) {
            readxl::excel_sheets(raw_xlsx_path)
          } else {
            "File not found"
          },
          selected = if (file.exists(raw_xlsx_path)) {
            readxl::excel_sheets(raw_xlsx_path)[1]
          } else {
           "File not found"
          }
        )
    ),

    DT::dataTableOutput("raw_dataset_preview"),

    div(
    style="margin-top:0.7rem;background:#f8fafc;padding:0.7rem;border-radius:8px;border:1px solid #e2e8f0;",
    tags$em("Notice: Structure is implicit. Column names and relationships are not formally declared.")
  )
),

  # -------------------------
  # DATASET CONFIG
  # -------------------------
  tabPanel(
  "Dataset Config",

  checkboxInput("show_full_config", "Show full file", FALSE),

  tags$div(
    id = "dataset_config_box",
    verbatimTextOutput("dataset_config_yaml")
  ),

    div(
    style="margin-top:0.7rem;background:#f8fafc;padding:0.7rem;border-radius:8px;border:1px solid #e2e8f0;",
    tags$em(" Dataset configuration file links the raw data to a dataset profile and defines how the pipeline
     should interpret source files, sheets, and column names.")
)),

  # -------------------------
  # DATASET PROFILE
  # -------------------------
  tabPanel(
  "Dataset Profile",

  checkboxInput("show_full_profile", "Show full file", FALSE),

  tags$div(
    id = "dataset_profile_box",
    verbatimTextOutput("dataset_profile_yaml")
  ),

    div(
    style="margin-top:0.7rem;background:#f8fafc;padding:0.7rem;border-radius:8px;border:1px solid #e2e8f0;",
    tags$em("Profiles are curated structural templates that define required components,
     validation rules, and expected standards for this dataset type.")
)),

div(
  style="margin-top:0.7rem;",
  tags$b("Outcome: The dataset has a declared structure and a selected profile guiding its FAIRification path."
  )),

div(
  style="margin-top:0.2rem;font-size:0.97em;color:#2563EB;",
   tags$em("FAIR focus in this step: Reusable (R) foundation")
)
))}else if (identical(input$fair_step, "structure")) {
      div(
      class = step_class,
      style = paste0("border-left: 5px solid ", border_col, "; padding-left: 1.1rem;"),

  h3("Step 2 — Structure for reuse"),
  tags$small(style="color:#64748B;font-size:1.01em;", 
             "From flat spreadsheet to relational structure"),
  tags$hr(style="margin:0.7rem 0 1.1rem 0;"),

  p("After preparing your dataset and declaring the dataset profile in Step 1, the pipeline now understand what your dataset represents.
    In this step, the dataset is reorganized into a canonical relational structure that separates context, entities, and measurements."),

  p("Many ecological datasets begin as flat spreadsheets. While convenient for manual use,these  often mix sampling context, observed entities, and measured values into a single structure. 
    This makes computational reuse and integration difficult."),

  h4("Why this step matters"),

  p("Before restructuring, the dataset typically:"),
  tags$ul(
    tags$li("Repeat contextual information (e.g., plot, date) across many rows"),
    tags$li("Mixes events, organisms, and measurements in one table"),
    tags$li("Uses inconsistent formats and units"),
    tags$li("Lacks stable identifiers for linking observations"),
    tags$li("Encodes relationships implicitly rather than explicitly")
  ),

  p("Such structures are understandable to humans, but limit computational reuse and integration by machines."),

  h4("What happens in this step"),

  p("Based on the selected profile, the FAIRification pipeline reorganizes the dataset into structural components:"),

  tags$ul(
    tags$li(strong("Event table"), " — defines when and where sampling occurred"),
    tags$li(strong("Occurrence table"), " — defines what biological entity was observed"),
    tags$li(strong("Measurement table"), " — defines quantitative observations linked to occurrences")
  ),

  p(" Each table is assigned stable identifiers (e.g., eventID, occurrenceID, measurementID) and linked explicitly, ensuring that relationships between events, organisms, and measurements are traceable and consistent."),

  p("The dataset now follows a relational logic where connections between sampling events, organisms, and measurements are machine-traceable."),

  h4("What changes in this step"),

  p("While the ecological content remains the same:
    "),

  tags$ul(
    tags$li("Implicit relationships become explicit"),
    tags$li("Stable identifiers enable reliable joins"),
    tags$li("Context is separated from observation"),
    tags$li("The dataset becomes structurally reusable")
  ),

  p("The structure becomes explicit and machine-readable"),

  h4("Views"),

#-------------------------------------------------------------------------------
# Before & After paired view to illustrate the structural transformation - STEP 2
#--------------------------------------------------------------------------------
  tabsetPanel(
    id = "fair_step2_views",

    tabPanel(
      "Before",
      p("Flat spreadsheet structure mixing context and measurements."),
      tags$div(class = "row g-3 align-items-start step-images",
        tags$div(class = "col-12",
          tags$em("Context, entities, and measurements are mixed in a single table with implicit relationships."),
          tags$figure(class = "figure",
            tags$img(src = "s2v1.png", alt = "Before structure transformation"),
            tags$figcaption("Raw flat table: mixed context, entities and measurements")
          )
        ),
        tags$div(class = "col-12",
          tags$figure(class = "figure",
            tags$img(src = "s2v1.1.png", alt = "Before structure transformation 2"),
            tags$figcaption("Repeated context and inconsistent formatting across rows")
          )
        )
      )
    ),
    tabPanel(
      "Restructuring schema",
      p("Relational structure with explicit identifiers."),
       tags$div(class = "col-12",
          tags$figure(class = "figure",
            tags$img(src = "step2viz2.png", alt = "Before structure transformation 2")
            
          )
   )
        ),

    tabPanel(
      "After",
      p(" Relational structure with explicit identifiers applied to this dataset."),
      tags$div(class = "row g-3 align-items-start step-images",
        tags$div(class = "col-12",
          tags$em("Event, occurrence, and measurement tables with stable identifiers and explicit relationships."),
          tags$figure(class = "figure",
            tags$img(src = "s2v3.png", alt = "After structure transformation"),
            tags$figcaption("Separated tables with stable identifiers (event, occurrence, measurement)")
          )
        ),
        tags$div(class = "col-12",
          tags$figure(class = "figure",
            tags$img(src = "s2v3.3.png", alt = "After structure transformation 3")
          )
        )
      )
    ),
          div(style="margin-top:0.9rem;",
              tags$b("Outcome: The dataset now has an explicit relational structure with stable identifiers.")
              ),
          div(style="margin-top:0.2rem;font-size:0.97em;color:#10B981;",
          tags$em("FAIR focus in this step: Interoperable (I) & Reusable (R) foundation"))
  
  ))} else if (identical(input$fair_step, "standards")) {
      div(
      class = step_class,
      style = paste0("border-left: 5px solid ", border_col, "; padding-left: 1.1rem;"),
  h3("Step 3 — Apply standards & semantics"),
  tags$small(style="color:#64748B;font-size:1.01em;",
             "From structured data to shared scientific language"),
  tags$hr(style="margin:0.7rem 0 1.1rem 0;"),
  p("Even the clear structure alone is not enough."),
  p("Different studies often use different labeling, formats, and implicit meanings for the same concepts."),
  p("In this step you allign your dataset with community standards and vocabularies, making the meaning of your data explicit and machine-readable."),
  h4("Why this step matters"),
  p("Before standardization, datasets oftenly:"),
  tags$ul(
    tags$li("Uses local or inconsistent terms for key concepts"),
    tags$li("Lacks consitent terminology"),
    tags$li("Require manual interpretation"), 
    tags$li("Are difficuly to integrate with other datasets")
  ),
  p("Such datasets are not truly interoperable or reusable and require shared uderstanding or manual work to interpret and integrate."),
  h4("What you provide"),
  p("To apply standards you procvide:"),
  tags$ul(
    tags$li(strong("Mapping file"), "linking your dataset's columns and values to standard terms (e.g. Darwin Core)"),
    tags$li(strong("(Optional) Ontology references within the mapping file"), "to further clarify the meaning of your data (e.g. ENVO terms for habitat types)")
  ),
  p("The previous selected profile indicates which standards are most relevant for your dataset type, but you can choose which ones to apply."),
  p("Take a peak how to link your data to standards and ontologies at the bottom of this page."),
  h4("What happens in this step"),
  p("If a mapping file is provided, the FAIRification pipeline:"),
  tags$ul(
    tags$li("Applies the mapping rules"),
    tags$li("Converts data to standards"),
    tags$li("Ensures consistent formats and identifiers"),
    tags$li("Annotates data with ontology terms when available"),
    tags$li("Exports standardized dataset that you can download")

  ),
  p("Your dataset now communicates in a shared scientific language."),
  p("This step can be iterative as you refine your mappings and standards alignment."),
  hr(),

h4("Create a mapping file"),

p("To apply standards, create a mapping file that connects your dataset columns 
to community-standard terms."),

p("The mapping file is stored inside your dataset folder on your computer."),

tags$pre(
"my_dataset/
│
├── raw/
├── dataset.yaml
└── mappings/
    └── mapping.yaml"
),

p("You can create this file using any text editor or file manager — no programming software is required."),

tags$h5("How to create mapping.yaml"),

tags$ol(
  tags$li("Open your dataset folder on your computer."),
  tags$li("Create a new folder named ", tags$code("mappings"), "."),
  tags$li("Inside this folder, create a new file named ", tags$code("mapping.yaml"), "."),
  tags$li("Open the file using any text editor (e.g. Notepad, TextEdit, LibreOffice, VS Code)."),
  tags$li("Add mappings linking your dataset columns to standard terms."),
  tags$li("Save the file and return to the FAIRifier.")
),

div(
  style="margin-top:0.7rem;background:#f8fafc;padding:0.7rem;border-radius:8px;border:1px solid #e2e8f0;",
  tags$em(
    "The FAIRifier automatically detects mapping.yaml when present and applies semantic alignment during the pipeline."
  )
),

hr(),

h4("How mapping works"),

p("Mapping translates local column names into shared scientific meaning."),

tags$table(
  class="table table-sm",
  tags$thead(
    tags$tr(
      tags$th("Your column"),
      tags$th("Meaning"),
      tags$th("Standard term")
    )
  ),
  tags$tbody(
    tags$tr(tags$td("species"), tags$td("Observed organism"), tags$td("dwc:scientificName")),
    tags$tr(tags$td("plot"), tags$td("Sampling location"), tags$td("dwc:locationID")),
    tags$tr(tags$td("height"), tags$td("Measured value"), tags$td("dwc:measurementValue"))
  )
),

p("Each entry in mapping.yaml links one dataset column to a recognised standard term."),

tags$pre(
"columns:
  species:
    term: dwc:scientificName

  plot:
    term: dwc:locationID

  height:
    term: dwc:measurementValue"
),

div(
  style="margin-top:0.7rem;background:#ecfeff;padding:0.7rem;border-radius:8px;border:1px solid #67e8f9;",
  tags$strong("Tip: "),
  "You do not need to memorise standards. Search for matching concepts in community vocabularies such as Darwin Core."
),

tags$ul(
  tags$li(
    tags$a("Darwin Core Terms", href="https://dwc.tdwg.org/terms/", target="_blank")
  ),
  tags$li(
    tags$a("Environment Ontology (ENVO)", href="https://www.ebi.ac.uk/ols/ontologies/envo", target="_blank")
  )
),

hr(),
h4("Views"), 
#-------------------------------------------------------------------------------
# Before & After paired view to illustrate the structural transformation - STEP 3
#--------------------------------------------------------------------------------
  tabsetPanel(
    id = "fair_step3_views",

    tabPanel(
      "Mapping File",
      checkboxInput("show_full_mapping", "Show full mapping file", FALSE),

      tags$div(
        id = "mapping_box",
        verbatimTextOutput("mapping_yaml")
      ),

      div(
        style="margin-top:0.7rem;background:#f8fafc;padding:0.7rem;border-radius:8px;border:1px solid #e2e8f0;",
        tags$em("How to link your dataset to standards and ontologies: the mapping file defines
         how your columns and values correspond to standard terms, enabling the pipeline to transform your data
        into a standardized format.")
      )
    ),

     tabPanel(
      "After",
      p("Canonical relational structure with explicit identifiers."),
      tags$div(class = "row",
        tags$div(class = "col-6",
          tags$em("Event, occurrence, and measurement tables with stable identifiers and explicit relationships."),
          tags$img(src = "s3after.png", alt = "After structure transformation",
                   style = "width:100%; height:auto; border-radius:8px; border:1px solid #e2e8f0;")
        ),
        tags$div(class = "col-6",
          tags$img(src = "s3after1.png", alt = "After structure transformation 3",
                   style = "width:100%; height:auto; border-radius:6px; border:1px solid #e2e8f0;")
        )
      )
    ),
          div(style="margin-top:0.9rem;",
              tags$b("Outcome: The dataset is now aligned with community standards and uses shared terminology.")
              ),
          div(style="margin-top:0.2rem;font-size:0.97em;color:#3B82F6;",
          tags$em("FAIR focus in this step: Interoperable (I) & Reusable (R) foundation")

  )))} else if (identical(input$fair_step, "metadata")) {
      div(
      class = step_class,
      style = paste0("border-left: 5px solid ", border_col, "; padding-left: 1.1rem;"),
     h3("Step 4 — Generate FAIR metadata"),
    tags$small(style="color:#64748B;font-size:1.01em;",
           "From structured data to documented research object"),
    tags$hr(style="margin:0.7rem 0 1.1rem 0;"),

  p("Once your dataset is structured (Step 2) and aligned with standards (Step 3), 
  the pipeline can generate a  metadata draft describing your dataset."),

  p("Metadata is data about data. 
  It explains what the dataset contains, how it was created, and under what conditions it may be reused."),

  h4("Why this step matters"),

  p("Without formal metadata, a dataset may:"),
  tags$ul(
    tags$li("Be difficult to discover in repositories"),
    tags$li("Lack documented methods or provenance"),
    tags$li("Have unclear licensing or reuse conditions"),
    tags$li("Be hard to interpret outside its original research context")
  ),
  p("FAIR metadata makes datasets understandable, searchable, and reusable beyond their original project."),

  h4("What happens in this step"),

  p("Based on your structured data, configuration, selected profile, and any optional metadata files you provide, the pipeline:"),

  tags$ul(
    tags$li("Extracts structural information from the dataset"),
    tags$li("Incorporates user-provided metadata (e.g., .txt, .docx, .yaml) when available"),
    tags$li("Applies a community metadata standard template (e.g., EML)"),
    tags$li("Generates a machine-readable metadata draft"),
    tags$li("Exports the metadata draft plus a checklist of remaining metadata elements that may require your review or completion")
),

p("If you provide additional documentation files (study descriptions, methods, notes), 
the pipeline integrates this information into the structured metadata draft."),

h4("What you may refine"),

p("Certain elements typically require researcher review or completion, such as:"),

tags$ul(
  tags$li("Abstract and study context"),
  tags$li("Detailed methods and sampling design"),
  tags$li("Funding and acknowledgements"),
  tags$li("Licensing decisions")
),

p("The exported draft can be refined using guided instructions from the FAIRification pipeline or by using metadata editing tools that support the chosen standard."),

h4("What changes"),

p("Structured dataset → Documented research object"),

tags$ul(
  tags$li("A standards-aligned metadata draft is generated"),
  tags$li("Dataset structure and context become explicit"),
  tags$li("Provenance and access conditions are documented"),
  tags$li("The dataset becomes repository-ready in principle")
),

  h4("Views"),  
  tabsetPanel(
    id = "fair_step4_views",

    tabPanel(
      "Metadata Draft",
      checkboxInput("show_full_metadata_draft", "Show full file", FALSE),

      tags$div(
        id = "metadata_draft_box",
        verbatimTextOutput("metadata_draft_preview")
      )
    ),
    


    tabPanel(
      "ezEML Editor",
      p("The generated metadata draft can be refined and fully standardized using the ezEML Editor. For editing online, see ",
        tags$a("ezEML (Metadata Editor)", href = "https://ezeml.edirepository.org/eml/about", target = "_blank"), 
        ""),
      tags$div(style="margin-top:0.6rem;",
               tags$em("Using ezEML Editor, you can review and enhance the generated metadata draft, ensuring that all necessary information is accurately captured and formatted according to the EML standard."))
              ),
          div(style="margin-top:0.9rem;",
            tags$b("Outcome: A machine-readable metadata record describes the dataset’s structure, provenance, and access conditions.")
          ),
           div(style="margin-top:0.2rem;font-size:0.97em;color:#7C3AED;",
          tags$em("FAIR focus in this step: Findable (F) prepared, Accessible (A) described, Reusable (R) documented")
)
  ))} else if (identical(input$fair_step, "validate")) {
      div(
      class = step_class,
      style = paste0("border-left: 5px solid ", border_col, "; padding-left: 1.1rem;"),
      h3("Step 5 — Validate and package"),
tags$small(style="color:#64748B;font-size:1.01em;",
           "From standardized data and metadata to FAIR-ready package"),
tags$hr(style="margin:0.7rem 0 1.1rem 0;"),

p("At this stage, your dataset has structure, standards, and metadata. 
The pipeline now verifies that everything aligns with the declared profile and standards — and prepares a complete, reusable research package."),

h4("Why this step matters"),

p("Before validation, even well-prepared datasets may still contain hidden inconsistencies or incomplete components."),

tags$ul(
  tags$li("Structural mismatches with the selected profile"),
  tags$li("Missing identifiers or broken links between tables"),
  tags$li("Incomplete metadata fields"),
  tags$li("Inconsistent vocabulary or formatting"),
  tags$li("No clear distribution bundle")
),

p("Without validation and packaging, reuse remains uncertain."),

h4("What happens in this step"),

p("The FAIRification pipeline performs automated checks and produces:"),

tags$ul(
  tags$li(strong("Validation report"), 
          " — documents structural checks, profile compliance, and standard alignment"),
  tags$li(strong("Advanced folder"), 
          " — full internal outputs, logs, and QA artifacts"),
  tags$li(strong("Publication folder"), 
          " — clean, standardized data tables and machine-readable metadata"),
  tags$li(strong("README file"), 
          " — explains package structure and reuse guidance"),
  tags$li(strong("FAIR-ready archive (.zip)"), 
          " — reproducible bundle prepared for repository submission")
),

p("Validation is an automated process that verifies consistency and completeness of the dataset and metadata."),

h4("What changes"),

p("Standardized dataset → Verified FAIR-ready package"),

tags$ul(
  tags$li("Compliance with the selected profile is checked"),
  tags$li("Standards and vocabulary alignment are verified"),
  tags$li("Metadata completeness is assessed"),
  tags$li("All components are bundled into a reusable distribution package")
),

p("The result is a reproducible research object that can be shared, reviewed, or published."),

  h4("Views"),  
  tabsetPanel( 
    id = "fair_step5_views",

    tabPanel(
      "Validation Report",
      checkboxInput("show_full_validation_report", "Show full report", FALSE),
      tags$div(
        id = "validation_report_box",
        verbatimTextOutput("validation_report_preview")
      )
    ),


    tabPanel(
      "Package Contents",
      p("Overview of the files and structure of the packaged dataset."),
      tags$pre("
walking_forest_2025_latest/
│
├── advanced/
│   ├── config/
│   ├── data/
│   ├── provenance/
│   └── validation/
│
├── publication/
│   ├── data/
│   │   └── dwc/
│   │       ├── event.csv
│   │       ├── occurrence.csv
│   │       └── measurement_or_fact.csv
│   │
│   ├── metadata/
│   │   ├── eml_draft.xml
│   │   ├── ezEML_generation_instructions.txt
│   │   ├── metadata.jsonld
│   │   └── ro-crate-metadata.json
│   │
│   └── README_package.txt
│
└── walking_forest_2025_latest.zip"
)      )
    ),

          div(style="margin-top:0.9rem;",
            tags$b("Outcome: A validated, standards-aligned dataset is packaged and ready for reuse.")
          ),
           div(style="margin-top:0.2rem;font-size:0.97em;color:#DB2777;",
          tags$em("FAIR focus in this step: Findable (F) prepared, Accessible (A) described, Interoperable (I) aligned, Reusable (R) verified")

  ))} else if (identical(input$fair_step, "publish")) {
  div(
    class = step_class,
    style = paste0("border-left: 5px solid ", border_col, "; padding-left: 1.1rem;"),
    h3("Step 6 — Publish and assess FAIRness (beyond the pipeline)"),
    tags$small(style="color:#64748B;font-size:1.01em;",
             "From FAIR-ready package to publicly available research object"),
    tags$hr(style="margin:0.7rem 0 1.1rem 0;"),

  p("The FAIRification pipeline concludes in Step 5 with a validated, 
    standards-aligned dataset as a reusable research package. At this point, your dataset is technically FAIR-ready — but it is not yet publicly visible."),
  
  p("Publication is not automated and happens outside the pipeline."),
  p("Whether to publish, when to publish, and under what conditions is a decision made by the data owner or responsible institution."),

  h4("Why this step is separate from the pipeline"), 
  p("A dataset can be technically FAIR-ready without being publicly released"), 
  p("Publication may depend on:",

  tags$ul(
    tags$li("Sensitive or restricted data"),
    tags$li("Embargo periods"),
    tags$li("Institutional or legal policies"),
    tags$li("Ongoing research considerations"),
    tags$li("Licensing and intellectual property agreements")
  )),

  p("The pipeline prepares the dataset for publication; the data owner decides whether and how is shared with the public."),

  h4("Why this step matters"),

  p("FAIR readiness does necessarily not mean FAIR in practice.
  A dataset only becomes truly:",
  tags$ul(
    tags$li("Findable (F) when it has a persistent identifier(e.g. DOI)"),
    tags$li("Accessible (A) when access conditions are clearly defined and operational"),
    tags$li("Interoperable (I) when it is published with its metadata and standards in place"),
    tags$li("Reusable (R) when it is released with clear licensing and documented provenance")
  )),
  p("Without publication, the dataset may be well prepared internally and FAIR-ready but remains invisible to research communities."),

  h4("What changes in this step"),

  p("If publication is chosen:"),

  tags$ul(
    tags$li("The dataset becomes globally findable"),
    tags$li("Access conditions become operational"),
    tags$li("The dataset becomes formally citable"),
    tags$li("Independent FAIR assessment becomes possible"),
    tags$li("The dataset enters long-term stewardship")
  ),

  p("If publication is not chosen, the dataset remains internally FAIR-ready 
    and structurally compliant, but not publicly discoverable and accessible."),

h4("Views"),

tabsetPanel(
  id = "fair_step6_views",

  # -------------------------
  # PUBLICATION VIEW
  # -------------------------
  tabPanel(
    "Publication",

    p("If the data owner chooses to publish, the FAIR-ready package can be deposited in a trusted repository."),

    tags$ul(
      tags$li(strong("Persistent identifier (DOI or Handle)"),
              " — makes the dataset globally resolvable and citable"),
      tags$li(strong("Public landing page"),
              " — human-readable description with structured metadata"),
      tags$li(strong("Metadata indexing"),
              " — harvested by search engines and aggregators"),
      tags$li(strong("Access & licensing declaration"),
              " — defines reuse conditions"),
      tags$li(strong("Versioning"),
              " — enables traceability and citation stability")
    ),

    tags$div(
      style="margin-top:0.8rem;background:#f8fafc;padding:0.8rem;border-radius:8px;border:1px solid #e2e8f0;",
      tags$em("Publication activates Findable (F) and Accessible (A) dimensions in practice.")
    )
  ),

  # -------------------------
  # FAIR ASSESSMENT VIEW
  # -------------------------
  tabPanel(
    "FAIR Assessment (external)",

    p("FAIR assessment is typically performed outside the pipeline.
      Different tools support evaluation at different stages of a dataset’s lifecycle —
      from internal preparation to published repository records."),

    h5("Pre-publication / Internal readiness"),
    tags$ul(
      tags$li(
        tags$a("FAIR-Aware (DANS)",
               href = "https://fairaware.dans.knaw.nl/",
               target = "_blank"),
        " — guided self-assessment of FAIR awareness and maturity"
      ),
      tags$li(
        tags$a("FAIRset (LTER-LIFE)",
               href = "https://lter-life-experience.org/fairset/",
               target = "_blank"),
        " — evaluates structural readiness and FAIR alignment, including offline datasets"
      )
    ),

    h5("Post-publication / Repository record"),
    tags$ul(
      tags$li(
        tags$a("F-UJI Automated FAIR Evaluation Tool",
               href = "https://www.f-uji.net",
               target = "_blank"),
        " — automated FAIR evaluation of publicly accessible DOI records"
      )
    ),

    h5("Conceptual framework"),
    tags$ul(
      tags$li(
        tags$a("FAIRmetrics.org",
               href = "https://fairmetrics.org",
               target = "_blank"),
        " — FAIR maturity indicators and evaluation principles"
      )
    ),

    tags$div(
      style="margin-top:0.8rem;background:#f8fafc;padding:0.8rem;border-radius:8px;border:1px solid #e2e8f0;",
      tags$em("FAIR evaluation may focus on internal readiness, structural compliance, or public repository records, depending on the dataset’s stage.")
    )
  )
))}

#likely will be deleted or improved... so far not visible in all 6 steps, but can be used to add a consistent summary box in each step if desired
    else {
    div(
    class = step_class,
    div(
    style = paste0("background:#FAFAFA;padding:0.6rem 0.9rem;border-radius:10px;margin-bottom:0.8rem;border-left:4px solid ", border_col, "; "),
          strong("You are here: "),
          textOutput("fair_stage_summary", inline = TRUE)
        ),
        p(
          class = "text-muted",
          style = "font-size: 0.9rem; margin-bottom: 0.6rem;",
          "Follow how the Walking Forest dataset moves from raw table to FAIR-ready package in six steps."
        ),
        hr(),
        span(
          class = "card-helper",
          style = "display:block; font-size: 0.85rem; margin-bottom: 0.4rem; color: #111827;",
          "Use the views below to inspect how this step looks in practice."
        ),
        uiOutput("fair_step_views_tabs")
      )
    }
  })

# =================================================================
# STEPs — : Raw + Config + Profile + Standard + Metadata previews
# =================================================================

# Define base dataset paths once  
datasets_root <- "../data-automation/datasets"

raw_xlsx_path <- file.path(
  datasets_root,
  "walking_forest",
  "raw",
  "walking_forest_2025.xlsx"
)

dataset_yaml_path <- file.path(
  datasets_root,
  "walking_forest",
  "dataset_app.yaml"
)

profile_yaml_path <- file.path(
  datasets_root,
  "profiles",
  "ecology.yaml"
)

# Example mapping file path for the demo dataset (used in Step 3 UI)
mapping_yaml_path <- file.path(
  datasets_root,
  "walking_forest",
  "mappings",
  "dwc_standard_app.yaml"
)

# Example metadata draft path for the demo dataset (used in Step 4 UI)
metadata_draft_path <- file.path(
  datasets_root,
  "walking_forest",
  "metadata",
  "eml_draft.xml"
)

# Example for validation report path (used in Step 5 UI)
validation_report_path <- file.path(
  datasets_root,
  "walking_forest",
  "packages",
  "walking_forest_2025_latest",
  "advanced",
  "validation",
  "qa_report.json"
)

# Example package path for download link in Step 5 UI
package_path <- file.path(
  datasets_root,  
  "walking_forest",
  "packages",
  "walking_forest_2025_latest",
  "publication",
  "walking_forest_2025_publication.zip",
  "advanced"
)

# -------------------------
# RAW DATASET PREVIEW
# -------------------------
output$raw_dataset_preview <- DT::renderDataTable({

  req(input$raw_sheet_select)

  if (!file.exists(raw_xlsx_path)) {
    return(
      DT::datatable(
        data.frame(Error = "Raw Excel file not found."),
        options = list(dom = "t"),
        rownames = FALSE
      )
    )
  }

  sheet_names <- readxl::excel_sheets(raw_xlsx_path)

  if (!(input$raw_sheet_select %in% sheet_names)) {
    return(
      DT::datatable(
        data.frame(Error = "Selected sheet not found in Excel file."),
        options = list(dom = "t"),
        rownames = FALSE
      )
    )
  }

  df <- readxl::read_excel(
    raw_xlsx_path,
    sheet = input$raw_sheet_select
  )

  DT::datatable(
    head(df, 10),
    options = list(scrollX = TRUE, pageLength = 10),
    rownames = FALSE
  )
})

# -------------------------
# DATASET CONFIG YAML
# -------------------------

output$dataset_config_yaml <- renderText({
  if (!file.exists(dataset_yaml_path)) return("dataset.yaml not found.")

  txt <- readLines(dataset_yaml_path, warn = FALSE)
  preview <- if (isTRUE(input$show_full_config)) txt else head(txt, 30)

  paste(preview, collapse = "\n")
})


# -------------------------
# DATASET PROFILE YAML
# -------------------------
output$dataset_profile_yaml <- renderText({
  if (!file.exists(profile_yaml_path)) return("dataset_profile.yaml not found.")

  txt <- readLines(profile_yaml_path, warn = FALSE)
  preview <- if (isTRUE(input$show_full_profile)) txt else head(txt, 30)

  paste(preview, collapse = "\n")
})

# -------------------------
# MAPPING FILE PREVIEW
# -------------------------
output$mapping_yaml <- renderText({
  if (!file.exists(mapping_yaml_path)) return("mapping file not found.")

  txt <- readLines(mapping_yaml_path, warn = FALSE)
  preview <- if (isTRUE(input$show_full_mapping)) txt else head(txt, 60)

  paste(preview, collapse = "\n")
})

# ----------------------------------
# METADATA (eml.draft) PREVIEW
# ----------------------------------
output$metadata_draft_preview <- renderText({
  if (!file.exists(metadata_draft_path)) return("Metadata draft not found.")

  # Prefer xml2 for pretty printing, fall back to XML, otherwise raw
  formatted <- tryCatch({
    doc <- xml2::read_xml(metadata_draft_path)
    xml2::write_xml(doc, options = "format")
  }, error = function(e1) {
    tryCatch({
      doc2 <- XML::xmlParse(metadata_draft_path)
      XML::saveXML(doc2, indent = TRUE)
    }, error = function(e2) {
      paste(readLines(metadata_draft_path, warn = FALSE), collapse = "\n")
    })
  })

  lines <- unlist(strsplit(formatted, "\n"))
  # If formatting didn't produce newlines (single-line blob), insert breaks between tags
  if (length(lines) == 1) {
    formatted2 <- gsub(
      ">(\\s*)<",
      ">\\n<",
      formatted,
      perl = TRUE
    )
    lines <- unlist(strsplit(formatted2, "\\n"))
  }

  preview <- if (isTRUE(input$show_full_metadata_draft)) lines else head(lines, 200)

  paste(preview, collapse = "\n")
})

#-------------------------------------------
# Validation report (Q__A_json) PREVIEW
#--------------------------------------------
output$validation_report_preview <- renderText({
  if (!file.exists(validation_report_path)) return("Validation report not found.")
  txt <- readLines(validation_report_path, warn = FALSE)
  preview <- if (isTRUE(input$show_full_validation_report)) txt else head(txt, 80)
  paste(preview, collapse = "\n")
})

# ----------------------------------
# PACKAGE CONTENTS PREVIEW
# ----------------------------------
observe({
  # discover available package folders for the demo dataset
  pkg_base <- file.path(datasets_root, "walking_forest", "packages")
  choices <- character(0)
  if (dir.exists(pkg_base)) {
    choices <- list.dirs(pkg_base, full.names = FALSE, recursive = FALSE)
    # filter out '.' or empty
    choices <- choices[choices != ""]
    # remove any accidental parent-name entries
    choices <- choices[basename(choices) != basename(pkg_base)]
  }
  if (length(choices) == 0) choices <- c("advanced", "publication")
  # update select input dynamically
  try({
    # preserve current selection when possible to avoid clobbering user choice
    sel <- NULL
    if (!is.null(isolate(input$package_choice)) && isolate(input$package_choice) %in% choices) {
      sel <- isolate(input$package_choice)
    } else {
      sel <- choices[1]
    }
    updateSelectInput(session, "package_choice", choices = choices, selected = sel)
  }, silent = TRUE)
})

# update variant selector when package changes
observeEvent(input$package_choice, {
  req(input$package_choice)
  pkg_base <- file.path(datasets_root, "walking_forest", "packages")
  pkg_dir <- file.path(pkg_base, input$package_choice)
  variants <- character(0)
  if (dir.exists(pkg_dir)) {
    variants <- list.dirs(pkg_dir, full.names = FALSE, recursive = FALSE)
    variants <- variants[variants != ""]
    # remove the package folder itself if present
    variants <- variants[basename(variants) != basename(pkg_dir)]
  }
  # if no variants, clear the selector
  if (length(variants) == 0) variants <- character(0)
  # preserve previous variant if still available
  selv <- NULL
  if (!is.null(isolate(input$package_variant)) && isolate(input$package_variant) %in% variants) {
    selv <- isolate(input$package_variant)
  } else if (length(variants) > 0) {
    selv <- variants[1]
  }
  try({ updateSelectInput(session, "package_variant", choices = variants, selected = selv) }, silent = TRUE)
})

# when user picks a variant, jump to that variant tab if it exists
observeEvent(input$package_variant, {
  req(input$package_variant)
  try({ updateTabsetPanel(session, "package_variant_tabs", selected = input$package_variant) }, silent = TRUE)
})

## Package variants UI: show subfolders (e.g. publication, advanced) inside a package
output$package_variants_ui <- renderUI({
  req(input$package_choice)
  pkg_base <- file.path(datasets_root, "walking_forest", "packages")
  pkg_dir <- file.path(pkg_base, input$package_choice)

  if (!dir.exists(pkg_dir)) {
    return(tags$div(class = "alert alert-warning", "Package folder not found."))
  }

  # find immediate subfolders (variants)
  variants <- list.dirs(pkg_dir, full.names = FALSE, recursive = FALSE)
  variants <- variants[variants != ""]

  if (length(variants) == 0) {
    # no variants — show a single table for package root
    tagList(
      DT::dataTableOutput("package_contents_dt_single")
    )
  } else {
    tabs <- lapply(variants, function(v) {
      tabPanel(
        title = v,
        fluidRow(
          column(3, downloadButton(paste0("download_variant_", v), paste0("Download ", v, " (.zip)"))),
          column(3, actionButton(paste0("refresh_variant_", v), "Refresh", class = "btn-secondary"))
        ),
        br(),
        DT::dataTableOutput(paste0("pkg_dt_", v))
      )
    })
    do.call(tabsetPanel, c(id = "package_variant_tabs", tabs))
  }
})

observeEvent(c(input$package_choice, input$refresh_package_list), {
  req(input$package_choice)
  pkg_base <- file.path(datasets_root, "walking_forest", "packages")
  pkg_dir <- file.path(pkg_base, input$package_choice)
  if (!dir.exists(pkg_dir)) return()

  variants <- list.dirs(pkg_dir, full.names = FALSE, recursive = FALSE)
  variants <- variants[variants != ""]

  if (length(variants) == 0) {
    # render single table of package root
    output$package_contents_dt_single <- DT::renderDataTable({
      files <- list.files(pkg_dir, recursive = TRUE, all.files = TRUE)
      if (length(files) == 0) return(DT::datatable(data.frame(Message = "Package is empty."), options = list(dom = "t")))
      full_paths <- file.path(pkg_dir, files)
      info <- file.info(full_paths, extra_cols = FALSE)
      df <- data.frame(
        path = files,
        size = ifelse(is.na(info$size), "", format(as.numeric(info$size), big.mark = ",")),
        mtime = as.character(info$mtime),
        stringsAsFactors = FALSE
      )
      DT::datatable(df, options = list(pageLength = 25, scrollX = TRUE), rownames = FALSE)
    })
  } else {
    # create renderers and download handlers per variant
    for (v in variants) {
      local({
        vv <- v
        outname <- paste0("pkg_dt_", vv)
        dlname <- paste0("download_variant_", vv)

        output[[outname]] <- DT::renderDataTable({
          variant_dir <- file.path(pkg_dir, vv)
          files <- list.files(variant_dir, recursive = TRUE, all.files = TRUE)
          if (length(files) == 0) return(DT::datatable(data.frame(Message = "Variant is empty."), options = list(dom = "t")))
          full_paths <- file.path(variant_dir, files)
          info <- file.info(full_paths, extra_cols = FALSE)
          df <- data.frame(
            path = files,
            size = ifelse(is.na(info$size), "", format(as.numeric(info$size), big.mark = ",")),
            mtime = as.character(info$mtime),
            stringsAsFactors = FALSE
          )
          DT::datatable(df, options = list(pageLength = 25, scrollX = TRUE), rownames = FALSE)
        })

        output[[dlname]] <- downloadHandler(
          filename = function() { paste0(input$package_choice, "_", vv, ".zip") },
          content = function(file) {
            variant_dir <- file.path(pkg_dir, vv)
            if (!dir.exists(variant_dir)) stop("Variant folder not found")
            wd <- normalizePath(variant_dir)
            oldwd <- setwd(wd)
            on.exit(setwd(oldwd), add = TRUE)
            files <- list.files(wd, recursive = TRUE)
            if (length(files) == 0) stop("Variant is empty")
            utils::zip(zipfile = file, files = files)
          }
        )
      })
    }
  }
})

  # ===================================================
  # Veluwe indicators (define BEFORE using in leaflet)
  # ===================================================
  veluwe_indicators <- data.frame(
    theme = c("Air", "Soil", "Hydrology", "Biodiversity"),
    lat = c(52.10, 52.12, 52.08, 52.11),
    lng = c(5.85, 5.90, 5.80, 5.88),
    indicator = c(
      "Annual mean NO₂",
      "Median topsoil organic C",
      "Median groundwater depth",
      "Forest bird richness"
    ),
    value = c("9", "3.1", "1.2", "34"),
    unit = c("µg/m³ (2023)", "% (0–10 cm)", "m (2022)", "species / km²"),
    dataset = c(
      "Luchtmeetnet – Veluwe stations",
      "Soil monitoring network (example)",
      "Provincial groundwater network (example)",
      "Breeding bird atlas (example)"
    ),
    source = c(
      "https://www.luchtmeetnet.nl/",
      "https://example.org/soil",
      "https://example.org/groundwater",
      "https://example.org/birds"
    ),
    stringsAsFactors = FALSE
  )

  # Veluwe region geometry (illustrative polygon)
  veluwe_coords <- matrix(c(
    5.75, 52.05,
    5.95, 52.05,
    5.95, 52.15,
    5.75, 52.15,
    5.75, 52.05
  ), ncol = 2, byrow = TRUE)

  veluwe_polygon <- st_polygon(list(veluwe_coords))
  veluwe_sf <- st_sfc(veluwe_polygon, crs = 4326)

  output$veluwe_map <- renderLeaflet({
    leaflet() %>%
      addTiles() %>%
      setView(lng = 5.85, lat = 52.10, zoom = 10) %>%
      addPolygons(
        data = veluwe_sf,
        color = "#1D4ED8",
        fillOpacity = 0.15,
        weight = 2,
        popup = "Veluwe region (illustrative)"
      ) %>%
      addCircleMarkers(
        lng = veluwe_indicators$lng,
        lat = veluwe_indicators$lat,
        radius = 6,
        stroke = TRUE,
        weight = 2,
        fillOpacity = 0.8,
        popup = paste0(
          "<strong>", veluwe_indicators$theme, "</strong><br>",
          veluwe_indicators$indicator, ": ", veluwe_indicators$value, " ", veluwe_indicators$unit, "<br>",
          "Dataset: <a href='", veluwe_indicators$source, "' target='_blank'>",
          veluwe_indicators$dataset, "</a>"
        )
      )
  })

  veluwe_card <- function(theme_name) {
    row <- veluwe_indicators[veluwe_indicators$theme == theme_name, , drop = FALSE]
    if (nrow(row) == 0) return(NULL)
    row <- row[1, ]

    tags$div(
      h4(row$indicator),
      p(tags$strong("Indicator: "), paste0(row$value, " ", row$unit)),
      p("Dataset: ", tags$a(row$dataset, href = row$source, target = "_blank")),
      tags$ul(
        tags$li("Curated, FAIR-ish dataset example for this theme."),
        tags$li("Designed to be integratable via shared spatial/temporal references."),
        tags$li("In a future release, this can be wired to actual FAIR packages.")
      )
    )
  }

  output$veluwe_air   <- renderUI(veluwe_card("Air"))
  output$veluwe_soil  <- renderUI(veluwe_card("Soil"))
  output$veluwe_hydro <- renderUI(veluwe_card("Hydrology"))
  output$veluwe_bio   <- renderUI(veluwe_card("Biodiversity"))

  # ===================================================
  # FAIR progress logic in sidebar
  # ===================================================
  # Reactive holder for optional package QA-derived completion

  observeEvent(input$load_pkg, {
    req(input$pkg_path)
    val <- tryCatch(compute_pipeline_completion(input$pkg_path), error = function(e) NULL)
    pkg_completion(val)
  })

  output$fair_step_counter <- renderUI({
    steps <- names(fair_journey_progress)
    idx <- match(input$fair_step, steps)
    if (is.na(idx)) idx <- 1

    span(
      class = "text-muted",
      style = "font-size: 0.85rem; margin-top: 0.25rem; display: inline-block;",
      paste0("Step ", idx, " of ", length(steps))
    )
  })

  output$fair_progress <- renderUI({
    step <- input$fair_step

    if (is.null(step) || !step %in% names(fair_journey_progress)) step <- "prepare"

    fair_val <- fair_journey_progress[[step]]

    stage_label <- c(
      prepare = "Dataset prepared",
      structure = "Structured for reuse",
      standards = "Standards & semantics applied",
      metadata = "FAIR metadata created",
      validate = "Validated & packaged",
      publish = "Published & externally assessed"
    )

    pipeline_status <- switch(
      step,
      prepare = "Pipeline: ingesting and preparing dataset.",
      structure = "Pipeline: structuring canonical tables.",
      standards = "Pipeline: applying mappings and vocabularies.",
      metadata = "Pipeline: generating machine-readable metadata.",
      validate = HTML("Pipeline: <strong>complete</strong> — FAIR-ready package built."),
      publish = HTML("Pipeline: <strong>complete</strong> — publication handled externally."),
      "Pipeline initializing."
    )

    detail_text <- if (step == "publish") {
      "Step 6 adds publication and external FAIR assessment; formal FAIR maturity and scores are determined using dedicated tools."
    } else {
      "Steps 1–5 are executed within the LTER-LIFE FAIRification pipeline and produce a FAIR-ready data package."
    }

    tagList(
      div(
        class = "fair-progress-label",
        strong(paste0("FAIRification journey completion: ", fair_val, "% — ", stage_label[[step]]))
      ),
      div(
        class = "fair-progress-wrapper",
        div(
          class = "progress fair-progress-track",
          div(
            class = "progress-bar fair-progress-bar",
            role = "progressbar",
            style = paste0("width:", fair_val, "%;"),
            `aria-valuenow` = fair_val,
            `aria-valuemin` = "0",
            `aria-valuemax` = "100"
          )
        )
      ),
      tags$small(
        class = "text-muted",
        style = "display: block; margin-top: 0.25rem; font-size: 0.8rem;",
        pipeline_status
      ),
      tags$small(
        class = "text-muted",
        style = "display: block; margin-top: 0.35rem; font-size: 0.8rem;",
        detail_text
      ),
      # If a package was loaded, show its computed pipeline completion
      if (!is.null(pkg_completion())) {
        tags$small(
          class = "text-muted",
          style = "display: block; margin-top: 0.35rem; font-size: 0.85rem;",
          HTML(paste0("Package QA-derived pipeline completion: <strong>", pkg_completion(), "%</strong>"))
        )
      }
    )
  })

  output$fair_step_badges <- renderUI({
    step <- input$fair_step
    classes <- list(F = "fair-letter", A = "fair-letter", I = "fair-letter", R = "fair-letter")

    if (!is.null(step)) {
      if (step == "structure") {
        classes$F <- "fair-letter active"
        classes$I <- "fair-letter active"
      } else if (step == "standards") {
        classes$I <- "fair-letter emphasis"
        classes$R <- "fair-letter active"
      } else if (step == "metadata") {
        classes$F <- "fair-letter active"
        classes$A <- "fair-letter active"
        classes$I <- "fair-letter active"
        classes$R <- "fair-letter active"
      } else if (step == "validate") {
        classes$R <- "fair-letter emphasis"
      } else if (step == "publish") {
        classes <- lapply(classes, function(x) "fair-letter active")
      }
    }

    div(
      class = "fair-badges",
      span(class = "fair-badge-label", "Emphasis now:"),
      span(
        class = "fair-badge-letters",
        span(class = classes$F, "F"),
        span(class = classes$A, "A"),
        span(class = classes$I, "I"),
        span(class = classes$R, "R")
      )
    )
  })

#this is nowhere to be seen in app atm-likely delete - was part of previous fair journey diagram concept
  output$fair_principle_emphasis <- renderUI({
    text <- switch(input$fair_step,
      prepare = "Foundation stage — FAIR aspects are emerging.",
      structure = "Advances Findability (F) and Interoperability (I).",
      standards = "Strongly improves Interoperability (I) and Reusability (R).",
      metadata = "Enhances Findability (F), Accessibility (A), and Reusability (R).",
      validate = "All FAIR dimensions are internally supported.",
      publish = "External assessment can evaluate full FAIR maturity."
    )
    span(class = "text-muted", text)
  })

  output$fair_step_title <- renderUI({
    switch(input$fair_step,
      prepare  = h3("Step 1 — Describe & prepare your data"),
      structure = h3("Step 2 — Structure for reuse"),
      standards = h3("Step 3 — Apply standards & semantics"),
      metadata = h3("Step 4 — Create FAIR metadata"),
      validate = h3("Step 5 — Validate & package"),
      publish = h3("Step 6 — Publish & assess FAIRness (optional)")
    )
  })

  output$fair_step_text <- renderUI({
    step <- input$fair_step
    if (is.null(step) || !(step %in% names(FAIR_STEPS))) return(NULL)
    fs <- FAIR_STEPS[[step]]
    tagList(
      p(fs$help),
      if (!is.null(fs$views)) tags$small(class = "text-muted", paste("Views:", paste(fs$views, collapse = " • ")))
    )
  })

  output$fair_view1 <- renderUI({
    step <- input$fair_step
    if (step == "prepare") {
      csv_preview <- user_csv_preview()
      tagList(
        div(class = "cleaning-panel",
            h5(id = "dataset_profile_label", "Dataset profile"),
            if (is.null(csv_preview)) {
              tagList(
                p("No file uploaded. Upload a CSV or use the sample dataset to start."),
                actionButton("load_sample_csv", "Load sample dataset", class = "btn-sm", `aria-label` = "Load sample dataset", tabindex = "0")
              )
            } else {
              tagList(
                tags$small(class = "text-muted", "Detected columns:"),
                tags$p(paste(names(csv_preview), collapse = ", ")),
                h5("Preview (first rows)"),
                tableOutput("user_csv_preview_table"),
                h5("Diagnostics"),
                tableOutput("user_csv_diag_table"),
                actionButton("analyze_user_dataset", "Analyze dataset", class = "btn-primary btn-sm", style = "margin-top:0.5rem;")
              )
            }
        ),
        div(style = "margin-top:0.6rem;", tags$small(class = "text-muted", "The profile helps you decide which cleaning and metadata steps to apply."))
      )

    } else if (step == "structure") {
      raw_tbl <- tags$table(
        class = "cleaning-table",
        tags$thead(tags$tr(tags$th("plot"), tags$th("dbh"), tags$th("date"), tags$th("notes"))),
        tags$tbody(
          tags$tr(tags$td("A1"), tags$td("30 cm"), tags$td("2024-05-01"), tags$td("")),
          tags$tr(tags$td("A1"), tags$td("0.32m"), tags$td("2024/05/01"), tags$td("different format")),
          tags$tr(tags$td("B2"), tags$td("?"), tags$td("01-05-24"), tags$td("missing value"))
        )
      )
      clean_tbl <- tags$table(
        class = "cleaning-table",
        tags$thead(tags$tr(tags$th("plot_id"), tags$th("diameter_mm"), tags$th("event_date"), tags$th("qc_flag"))),
        tags$tbody(
          tags$tr(tags$td("A-01"), tags$td("300"), tags$td("2024-05-01"), tags$td("ok")),
          tags$tr(tags$td("A-01"), tags$td("320"), tags$td("2024-05-01"), tags$td("ok")),
          tags$tr(tags$td("B-02"), tags$td(NA), tags$td("2024-05-01"), tags$td("check"))
        )
      )
      tagList(
        div(
          class = "cleaning-compare",
          div(class = "cleaning-panel", h5("Before"), raw_tbl),
          div(class = "cleaning-panel", h5("After"), clean_tbl)
        ),
        uiOutput("schema_diagram_ui"),
        uiOutput("schema_highlight_ui")
      )

    } else if (step == "standards") {
      tagList(
        div(class = "cleaning-panel",
          h5("Local → Standard mapping"),
          tags$table(
            class = "cleaning-table",
            tags$thead(tags$tr(tags$th("Local field"), tags$th("Standard term"), tags$th("Example value"))),
            tags$tbody(
              tags$tr(tags$td("species_name"), tags$td(tags$code("dwc:scientificName")), tags$td("Quercus robur")),
              tags$tr(tags$td("soil_type"), tags$td(tags$code("ENVO:00001998")), tags$td("peatland")),
              tags$tr(tags$td("unit"), tags$td(tags$code("UCUM:mm")), tags$td("mm"))
            )
          ),
          tags$small(class = "text-muted", "Mappings connect your local columns to community vocabularies so machines can interpret values.")
        ),
        div(style = "margin-top:0.6rem;",
          tags$strong("Why this matters:"),
          tags$p(class = "text-muted", "Applying standards and ontology identifiers makes the data interoperable and enables cross-dataset querying and automated reasoning.")
        )
      )

    } else if (step == "metadata") {
      pv <- pkg_preview()
      csv_preview <- user_csv_preview()
      tagList(
        div(class = "cleaning-panel",
            h5("Artifacts produced"),
            tags$div(style = "display:flex; gap:1rem; flex-wrap:wrap;",
                     div(style = "flex:1; min-width:240px;",
                         h6("EML"),
                         if (!is.null(pv$eml)) {
                           tagList(tags$p("EML file detected:"), tags$code(pv$eml))
                         } else {
                           tags$small(class = "text-muted", "No EML found in package.")
                         }
                     ),
                     div(style = "flex:1; min-width:240px;",
                         h6("JSON-LD / Schema"),
                         if (!is.null(pv$jsonld)) {
                           verbatimTextOutput("pkg_jsonld_text")
                         } else if (!is.null(sample_jsonld())) {
                           verbatimTextOutput("sample_jsonld_text")
                         } else {
                           tagList(tags$small(class = "text-muted", "No JSON-LD found."), tags$br(), actionButton("generate_sample_jsonld", "Generate sample JSON-LD", class = "btn-sm", `aria-label` = "Generate sample JSON-LD", tabindex = "0"))
                         }
                     ),
                     div(style = "flex:1; min-width:240px;",
                         h6("QA / Provenance"),
                         if (!is.null(pv$qa)) {
                           verbatimTextOutput("pkg_qa_text")
                         } else {
                           tags$small(class = "text-muted", "No QA report available.")
                         }
                     )
            ),
            tags$small(class = "text-muted", "These artifacts help catalog, discover and verify the dataset when shared.")
        ),
        div(style = "margin-top:0.6rem;", actionButton("preview_landing", "Preview landing page", class = "btn-sm", `aria-label` = "Preview landing page", tabindex = "0"), tags$span(" ", tags$small(class = "text-muted", "(Generates a lightweight landing page preview from available metadata)")))
      )

    } else if (step == "validate") {
      pv <- pkg_preview()
      completion <- pkg_completion()
      readiness <- "Needs work"
      if (!is.null(completion) && completion >= 90) readiness <- "FAIR-ready"

      div(class = "cleaning-panel",
          h5("Validation & packaging"),
          p(strong("Pipeline completion: "), ifelse(is.null(completion), "N/A", paste0(completion, "%"))),
          p(strong("Readiness: "), span(readiness, style = if (readiness == "FAIR-ready") "color:#10B981; font-weight:600;" else "color:#d97706; font-weight:600;")),
          tags$small(class = "text-muted", "Validation collects QA logs, schema checks and produces a packaged research object."),
          hr(),
          if (!is.null(pv$qa)) {
            tagList(
              h6("QA report (summary):"),
              verbatimTextOutput("pkg_qa_text")
            )
          } else {
            tags$small(class = "text-muted", "No QA report found in the loaded package.")
          }
      )

    } else if (step == "publish") {
      div(
        class = "cleaning-panel",
        h5("Repository record (illustrative)"),
        tags$strong("DOI: 10.1234/walking-forest.2025"), tags$br(),
        span("Title: Walking Forest ecological plots — FAIR-ready dataset"), tags$br(),
        span("Repository: Example Dataverse / Zenodo"), tags$br(),
        span("Files: data package + metadata + QA report"),
        tags$hr(),
        tags$strong("Post-publication checks:"),
        tags$ul(
          tags$li("Landing page with metadata and access instructions."),
          tags$li("Automated FAIR assessment runs against the public record."),
          tags$li("Persistent identifier resolves to the package and metadata files.")
        )
      )

    } else {
      p("Visual coming soon for this step.")
    }
  })

  output$fair_view2 <- renderUI({
    step <- input$fair_step

    if (step == "prepare") {
      tagList(
        h5("Cleaning decisions"),
        checkboxGroupInput(
          "decisions_prepare",
          label = NULL,
          choices = c(
            "Normalize units" = "normalize_units",
            "Standardize dates" = "standardize_dates",
            "Create stable IDs" = "create_ids",
            "Preserve notes column" = "preserve_notes"
          )
        ),
        tags$small(class = "text-muted", "Choose which transformations to apply during the cleaning step."),
        tags$div(style = "margin-top:0.6rem;", strong("Selected:"), uiOutput("decisions_summary"))
      )
    } else if (step == "structure") {
      tags$ul(
        tags$li("Units harmonized (cm/m → mm)."),
        tags$li("Dates normalized to ISO 8601 (YYYY-MM-DD)."),
        tags$li("Problematic values flagged instead of silently dropped.")
      )
    } else if (step == "standards") {
      tagList(
        tags$ul(
          tags$li("Local columns mapped onto standard terms (e.g. Darwin Core)."),
          tags$li("Ontology identifiers added for key concepts (e.g. ENVO, UCUM)."),
          tags$li("Metadata gains links that machines can follow.")
        ),
        tags$pre(
          style = "font-size: 0.75rem; background-color: #F9FAFB; border-radius: 8px; padding: 0.5rem;",
'{\n  "@context": "https://dwc.tdwg.org/context/dwc.jsonld",\n  "scientificName": "Quercus robur",\n  "eventDate": "2024-05-01",\n  "decimalLatitude": 52.05,\n  "decimalLongitude": 5.75\n}'
        )
      )
    } else if (step == "metadata") {
      tagList(
        div(class = "cleaning-panel",
          h5("Landing page preview"),
          uiOutput("landing_preview_ui")
        ),
        div(style = "margin-top:0.6rem;", tags$small(class = "text-muted", "The landing page presents human-readable metadata and links to machine-readable artifacts."))
      )
    } else if (step == "validate") {
      tags$ul(
        tags$li("Validation/QA report and logs produced."),
        tags$li("Data and metadata bundled for archiving and sharing."),
        tags$li("Package is ready for publication or further assessment.")
      )
    } else if (step == "publish") {
      tags$ul(
        tags$li("Dataset published with a persistent identifier (e.g. DOI)."),
        tags$li("External FAIR assessment tools (e.g. F-UJI) run against the public landing page."),
        tags$li("FAIR status can be revisited as standards and tooling evolve.")
      )
    } else {
      p("Narrative notes for this step will appear here.")
    }
  })

  output$fair_step_views_tabs <- renderUI({
    step <- input$fair_step
    if (!is.null(step) && step %in% names(FAIR_STEPS)) {
      labels <- FAIR_STEPS[[step]]$views
    } else {
      labels <- c("View 1", "View 2")
    }

    tabsetPanel(
      id = "fair_step_views",
      tabPanel(labels[1], uiOutput("fair_view1")),
      tabPanel(labels[2], uiOutput("fair_view2"))
    )
  })

  # ===================================================
  # FAIR toolkit demo (mock)
  # ===================================================
  user_fair_issues <- reactiveVal(NULL)

  # CSV preview and diagnostics
  user_csv_preview <- reactiveVal(NULL)
  user_csv_diagnostics <- reactiveVal(NULL)
  sample_jsonld <- reactiveVal(NULL)

  observeEvent(input$user_csv, {
    req(input$user_csv)
    path <- input$user_csv$datapath
    df <- tryCatch(read.csv(path, stringsAsFactors = FALSE), error = function(e) NULL)
    user_csv_preview(head(df, 20))

    # simple diagnostics
    required <- c("title", "license")
    cols <- tolower(names(df))
    missing <- setdiff(required, cols)
    diag <- data.frame(
      Check = c("Has rows", "Has columns", "Missing required columns"),
      Result = c(ifelse(nrow(df) > 0, "yes", "no"), paste(names(df), collapse = ", "), ifelse(length(missing)==0, "none", paste(missing, collapse = ", "))),
      stringsAsFactors = FALSE
    )
    user_csv_diagnostics(diag)
  })

  observeEvent(input$load_sample_csv, {
    # populate the CSV preview and diagnostics using the simulator's current state
    df <- tryCatch(sim_df(), error = function(e) NULL)
    if (!is.null(df)) {
      user_csv_preview(head(df, 20))
      required <- c("title", "license")
      cols <- tolower(names(df))
      missing <- setdiff(required, cols)
      diag <- data.frame(
        Check = c("Has rows", "Has columns", "Missing required columns"),
        Result = c(ifelse(nrow(df) > 0, "yes", "no"), paste(names(df), collapse = ", "), ifelse(length(missing) == 0, "none", paste(missing, collapse = ", "))),
        stringsAsFactors = FALSE
      )
      user_csv_diagnostics(diag)
    }
  })

  observeEvent(input$generate_sample_jsonld, {
    df <- user_csv_preview()
    if (is.null(df)) df <- head(sim_df(), 20)
    # simple JSON-LD sample derived from first row/columns
    if (!is.null(df) && nrow(df) > 0) {
      row <- df[1, , drop = FALSE]
      jsonld <- list(
        "@context" = "https://schema.org/",
        "@type" = "Dataset",
        "name" = ifelse(!is.null(row$title), as.character(row$title), "Sample dataset"),
        "description" = ifelse(!is.null(row$description), as.character(row$description), "Example dataset created by the FAIRifier demo."),
        "license" = ifelse(!is.null(row$license), as.character(row$license), "CC-BY-4.0"),
        "creator" = list("@type" = "Person", "email" = ifelse(!is.null(row$contact), as.character(row$contact), "dataset.owner@example.org"))
      )
      sample_jsonld(jsonlite::toJSON(jsonld, auto_unbox = TRUE, pretty = TRUE))
    }
  })

  output$sample_jsonld_text <- renderText({
    req(sample_jsonld())
    sample_jsonld()
  })

  observeEvent(input$preview_landing, {
    pv <- pkg_preview()
    csvp <- user_csv_preview()
    title <- NULL
    license <- NULL
    contact <- NULL
    if (!is.null(pv) && !is.null(pv$jsonld) && is.list(pv$jsonld)) {
      # try to extract simple fields
      if (!is.null(pv$jsonld$name)) title <- pv$jsonld$name
      if (!is.null(pv$jsonld$license)) license <- pv$jsonld$license
    }
    if (is.null(title) && !is.null(csvp) && "title" %in% tolower(names(csvp))) {
      title <- as.character(csvp[[which(tolower(names(csvp))=="title")]][1])
    }
    if (is.null(license) && !is.null(csvp) && "license" %in% tolower(names(csvp))) {
      license <- as.character(csvp[[which(tolower(names(csvp))=="license")]][1])
    }
    if (is.null(title)) title <- "Walking Forest sample"
    if (is.null(license)) license <- "CC-BY-4.0"
    if (is.null(contact)) contact <- "dataset.owner@example.org"

    landing <- tagList(
      div(class = "card", id = "landing_card", tabindex = "0", role = "region", `aria-live` = "polite", style = "padding:1rem;",
          h3(title),
          tags$p(tags$strong("License: "), license),
          tags$p(tags$strong("Contact: "), contact),
          tags$p(tags$strong("Description: "), "This is a lightweight landing page preview generated from available metadata."),
          tags$ul(tags$li(tags$a("EML file", href = "#")), tags$li(tags$a("JSON-LD", href = "#")))
      )
    )
    output$landing_preview_ui <- renderUI({ landing })
  })

  # -----------------------------
  # System 6: Lightweight dataset simulator
  # -----------------------------
  observeEvent(input$sim_next, {
    states <- c("Raw", "Cleaned", "Structured", "FAIR-ready")
    idx <- match(isolate(input$sim_state), states)
    if (is.na(idx)) idx <- 1
    new <- min(length(states), idx + 1)
    updateSelectInput(session, "sim_state", selected = states[new])
  })

  observeEvent(input$sim_prev, {
    states <- c("Raw", "Cleaned", "Structured", "FAIR-ready")
    idx <- match(isolate(input$sim_state), states)
    if (is.na(idx)) idx <- 1
    new <- max(1, idx - 1)
    updateSelectInput(session, "sim_state", selected = states[new])
  })

  sim_df <- reactive({
    state <- input$sim_state
    if (is.null(state)) state <- "Raw"
    if (state == "Raw") {
      data.frame(
        plot = c("A1","A1","B2"),
        dbh = c("30 cm","0.32m","?"),
        date = c("2024-05-01","2024/05/01","01-05-24"),
        notes = c("","different format","missing value"),
        stringsAsFactors = FALSE
      )
    } else if (state == "Cleaned") {
      data.frame(
        plot_id = c("A-01","A-01","B-02"),
        diameter_mm = c(300,320,NA),
        event_date = c("2024-05-01","2024-05-01","2024-05-01"),
        qc_flag = c("ok","ok","check"),
        stringsAsFactors = FALSE
      )
    } else if (state == "Structured") {
      data.frame(
        event_id = c("E1","E1","E2"),
        occurrence_id = c("O1","O2","O3"),
        measurement_id = c("M1","M2","M3"),
        measurementValue = c(30,32,NA),
        measurementUnit = c("cm","cm",NA),
        stringsAsFactors = FALSE
      )
    } else {
      data.frame(
        dataset_title = "Walking Forest sample",
        license = "CC-BY-4.0",
        contact = "dataset.owner@example.org",
        row_count = 3,
        stringsAsFactors = FALSE
      )
    }
  })

  output$sim_table <- renderTable({
    head(sim_df(), 10)
  }, rownames = FALSE)

  output$sim_state_desc <- renderUI({
    descs <- list(
      "Raw" = "Raw: messy user table with inconsistent formats and missing values.",
      "Cleaned" = "Cleaned: standardized field names and normalized values.",
      "Structured" = "Structured: data split into canonical tables (events, occurrences, measurements).",
      "FAIR-ready" = "FAIR-ready: packaged with metadata and persistent identifiers."
    )
    tags$small(class = "text-muted", descs[[input$sim_state]])
  })

  output$user_csv_preview_ui <- renderUI({
    req(user_csv_preview())
    tagList(
      h5("Preview (first 20 rows)"),
      tableOutput("user_csv_preview_table"),
      h5("Diagnostics"),
      tableOutput("user_csv_diag_table")
    )
  })

  output$user_csv_preview_table <- renderTable({
    user_csv_preview()
  })

  output$user_csv_diag_table <- renderTable({
    req(user_csv_diagnostics())
    user_csv_diagnostics()
  })

  # Package explorer: list files and preview common artifacts

  observeEvent(input$load_pkg, {
    req(input$pkg_path)
    p <- input$pkg_path
    if (dir.exists(p)) {
      files <- list.files(p, recursive = TRUE)
      pkg_file_list(files)

      # preview common files if present
      qa_path <- file.path(p, "advanced", "validation", "qa_report.json")
      eml_path <- list.files(p, pattern = "\\.xml$", recursive = TRUE, full.names = TRUE)
      jsonld_path <- list.files(p, pattern = "\\.jsonld$|\\.json$", recursive = TRUE, full.names = TRUE)

      preview <- list()
      if (file.exists(qa_path)) {
        preview$qa <- tryCatch(jsonlite::fromJSON(qa_path), error = function(e) NULL)
      }
      if (length(eml_path) > 0) {
        preview$eml <- eml_path[1]
      }
      if (length(jsonld_path) > 0) {
        preview$jsonld <- tryCatch(jsonlite::fromJSON(jsonld_path[1]), error = function(e) NULL)
      }
      pkg_preview(preview)
    } else {
      pkg_file_list(NULL)
      pkg_preview(NULL)
    }
  })

  output$pkg_files_ui <- renderUI({
    files <- pkg_file_list()
    if (is.null(files)) return(NULL)
    tagList(
      h5("Files in package (recursive)"),
      verbatimTextOutput("pkg_files_text")
    )
  })

  output$pkg_files_text <- renderText({
    paste(pkg_file_list(), collapse = "\n")
  })

  # Summarized package files view + toggle for developer drawer
  pkg_files_show_full <- reactiveVal(FALSE)
  observeEvent(input$pkg_files_show_full, {
    pkg_files_show_full(!isTRUE(pkg_files_show_full()))
  })

  output$pkg_files_summary <- renderText({
    files <- pkg_file_list()
    if (is.null(files)) return(NULL)
    if (length(files) == 1) {
      lines <- unlist(strsplit(files, "\n"))
    } else {
      lines <- files
    }
    paste(head(lines, 8), collapse = "\n")
  })

  output$pkg_files_full_ui <- renderUI({
    files <- pkg_file_list()
    if (is.null(files)) return(tags$small(class = "text-muted", "No package loaded."))
    if (!isTRUE(pkg_files_show_full())) {
      tagList(
        verbatimTextOutput("pkg_files_summary"),
        actionLink("pkg_files_show_full", "Show full")
      )
    } else {
      tagList(
        verbatimTextOutput("pkg_files_text"),
        actionLink("pkg_files_show_full", "Show summary")
      )
    }
  })

  output$pkg_preview_ui <- renderUI({
    pv <- pkg_preview()
    if (is.null(pv)) return(NULL)
    tagList(
      if (!is.null(pv$qa)) {
        h5("QA report summary (qa_report.json)")
      },
      if (!is.null(pv$qa)) verbatimTextOutput("pkg_qa_text"),
      if (!is.null(pv$jsonld)) {
        h5("Sample JSON-LD / JSON preview")
      },
      if (!is.null(pv$jsonld)) verbatimTextOutput("pkg_jsonld_text"),
      if (!is.null(pv$eml)) {
        h5("EML file (path)")
      },
      if (!is.null(pv$eml)) verbatimTextOutput("pkg_eml_text")
    )
  })

  output$pkg_qa_text <- renderText({
    pv <- pkg_preview()
    if (is.null(pv$qa)) return(NULL)
    jsonlite::prettify(jsonlite::toJSON(pv$qa, auto_unbox = TRUE))
  })

  output$pkg_jsonld_text <- renderText({
    pv <- pkg_preview()
    if (is.null(pv$jsonld)) return(NULL)
    jsonlite::prettify(jsonlite::toJSON(pv$jsonld, auto_unbox = TRUE))
  })

  output$pkg_eml_text <- renderText({
    pv <- pkg_preview()
    if (is.null(pv$eml)) return(NULL)
    pv$eml
  })

  observeEvent(input$analyze_user_dataset, {
    user_fair_issues(
      data.frame(
        Category = c("Metadata", "Structure", "Semantics"),
        Issue = c(
          "No title or license column detected.",
          "Columns with mixed types or unclear IDs.",
          "No standard vocabulary or ontology terms detected."
        ),
        stringsAsFactors = FALSE
      )
    )
  })

  # Render decisions summary inside an ARIA live region for screenreaders
  output$decisions_summary <- renderUI({
    sel <- input$decisions_prepare
    txt <- if (is.null(sel) || length(sel) == 0) "None" else paste(sel, collapse = ", ")
    tags$span(id = "decisions_summary_region", `aria-live` = "polite", tabindex = "0", txt)
  })

  output$user_fair_issues <- renderTable({
    req(user_fair_issues())
    user_fair_issues()
  })
}

shinyApp(ui = ui, server = server)
