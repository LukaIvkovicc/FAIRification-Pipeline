Data Dashboard (R)
===================

This folder contains an interactive R/Shiny dashboard for exploring datasets and pipeline outputs produced by the ETL pipeline.

App entry & expected layout
---------------------------
- Main app entry: `app.R` (the Shiny app). Static web assets live in `www/`.
- The app can display one or more local "FAIR package" directories placed in `data-dashboard/fair_packages/`.
	- Each package should look like a pipeline publication package (example: `walking_forest_2025_latest`) and may contain `advanced/validation/qa_report.json` and a `publication/data` folder with exported files. The app uses these artifacts to compute pipeline completion and populate views.

Run locally (R required)
-----------------------
From the project root (recommended):

```bash
# start the Shiny app (opens in your browser)
R -e "shiny::runApp('data-dashboard', launch.browser=TRUE)"
```

Or from within an R session:

```r
setwd('data-dashboard')
shiny::runApp()
```

To serve on all interfaces (useful in Docker or remote testing):

```bash
R -e "shiny::runApp('data-dashboard', host='0.0.0.0', port=3838)"
```

Required R packages
-------------------
The app loads several packages; install them before running the app:

```r
install.packages(c('shiny','bslib','jsonlite','leaflet','sf','here','DT','readxl','dplyr','ggplot2'))
```

Note: `sf` requires system dependencies (GEOS/GDAL/PROJ). On Debian/Ubuntu install these first:

```bash
sudo apt-get update && sudo apt-get install -y libudunits2-dev libgdal-dev libgeos-dev libproj-dev
```

Data / pipeline outputs (how to provide datasets)
-------------------------------------------------
The dashboard expects pipeline outputs packaged under `data-dashboard/fair_packages/`.
You can either copy or symlink a pipeline package into that folder. Example (from project root):

```bash
mkdir -p data-dashboard/fair_packages
# copy a pipeline publication package into the dashboard folder (example)
cp -r datasets/walking_forest/publication/ data-dashboard/fair_packages/walking_forest_2025_latest/
# or create a symlink to a local package
ln -s $(pwd)/datasets/walking_forest/ data-dashboard/fair_packages/walking_forest_2025_latest
```

The app reads `advanced/validation/qa_report.json` (if present) to compute a simple pipeline completion score and looks for exported data under the package's `publication/data` or `processed` locations.

Docker (example)
-----------------
Use `rocker/shiny` as a lightweight base to run the app in a container. Minimal `Dockerfile` example:

```dockerfile
FROM rocker/shiny:latest
COPY . /srv/shiny-server/data-dashboard
WORKDIR /srv/shiny-server/data-dashboard
# install R packages (adjust CRAN mirror as needed)
RUN R -e "install.packages(c('shiny','bslib','jsonlite','leaflet','sf','here','DT','readxl','dplyr','ggplot2'), repos='https://cloud.r-project.org')"
EXPOSE 3838
CMD ["R", "-e", "shiny::runApp('.', host='0.0.0.0', port=3838)"]
```

Run the container:

```bash
docker build -t lter-dashboard:data .
docker run -p 3838:3838 -v $(pwd)/data-dashboard/fair_packages:/srv/shiny-server/data-dashboard/fair_packages lter-dashboard:data
```

Troubleshooting
---------------
- If `sf` installation fails, ensure system GDAL/GEOS/PROJ development libraries are present (see above).
- If maps or spatial layers do not render, confirm your package contains spatial files or exported `processed` data the app can read.
- If the dashboard shows no datasets, verify directories under `data-dashboard/fair_packages/` follow the `<dataset>_latest` naming convention and contain a minimal pipeline package (or a `publication/data` folder).

Contact / issues
-----------------
Open an issue in this repository or contact the maintainers if you need help wiring a specific dataset into the dashboard.

 (This README was expanded to include `app.R` usage, dependencies, and how to point the dashboard at pipeline outputs.)
