## Configuration

1. Rename `config_template.json` to `config.json`.
2. Fill in your site-specific settings:
   - `site_name` — your site's identifier (used in output file names).
   - `data_directory` — path to the directory holding your CLIF table files
     (`clif_vitals.parquet`, `clif_labs.parquet`, …). **Defaults to the bundled `clif_demo/`
     dataset so the templates run out of the box; change it to your site's CLIF tables directory
     for a real run.**
   - `filetype` — `"csv"` or `"parquet"`.
   - `timezone` — your data's timezone, e.g. `"US/Eastern"` (required by clifpy).
    - `output_directory` — where clifpy writes logs and validation results (e.g. `"./output"`).
    - `imv_window_before_minutes` — minutes before the index paralytic included when detecting
      a non-IMV to IMV transition. Set to `30` for this study.
    - `imv_window_after_minutes` — minutes after the index paralytic included when detecting
      a non-IMV to IMV transition. Set to `60` for this study.
    - `sedation_window_minutes` — symmetric window around the index paralytic for retaining
      sedative administrations. Set to `5` for this study.
     - `medication_dose_units` — the one exact dose unit retained for each study medication.
      Use `mg` or `mg/kg` for non-fentanyl medications and `mcg` or `mcg/kg` for fentanyl.
      Units are normalized to lowercase before matching; rows in every other unit are excluded.
     - `medication_dose_upper_bounds` — the strict absolute-unit upper bound for each study
       medication. Eligible absolute doses are finite and satisfy `0 < dose < upper bound`;
       configured `/kg` units must still be positive and finite but bypass these absolute bounds.
       Fentanyl's bound is in `mcg`; all other bounds are in `mg`.

This file uses the **clifpy config schema**, so the Python templates can read it directly with
`ClifOrchestrator(config_path="config/config.json")`, and the R templates read the same fields via
`utils/config.R`. You can add or remove attributes based on project requirements.

Note: the `.gitignore` in this directory keeps `config.json` out of the remote repository.
