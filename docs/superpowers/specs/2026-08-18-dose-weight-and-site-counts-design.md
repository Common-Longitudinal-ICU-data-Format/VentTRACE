# Dose/Weight and Site Counts - Design Amendment

**Project:** VentTRACE  
**Date:** 2026-08-18  
**Status:** Implemented

This amendment adds P46. P2-P45 remain in force.

## P46

VentTRACE publishes an additive weight-normalized dose analysis and block-first event counts by
healthcare system, event-time hospital, academic status, and calendar year.

### Event Counts

- One event is the `p_num == 1` paralytic-index event in each encounter block.
- This is an operational, intubation-adjacent count, not a confirmed endotracheal-intubation count.
- `healthcare_system` is `config["site_name"]`.
- Hospital and `hospital_type` come from the ADT interval covering event time. `academic` maps to
  academic; every other non-null type maps to non-academic; unresolved values remain unknown.
- The shareable aggregate is `step04__intubations_by_hospital_year.csv`; Figure H.1 publishes the
  same rows as `fig_H1__intubations_by_hospital_year.csv` and plots one yearly line per hospital,
  colored by academic status.

### Dose Weight

The selected dose-normalization weight is separate from Table 1's existing weight and does not
change it:

1. Use the latest finite 20-300 kg weight at or before the event in the hospitalization containing
   the event.
2. If absent, use the latest finite 20-300 kg weight recorded before the event in a prior
   hospitalization for the patient, limited to 28 days before the event.
3. Future, missing, non-finite, and out-of-range values are ineligible. Timestamp ties are resolved
   deterministically.

P47 supersedes the original conversion rule. A configured absolute unit is divided by the
selected weight exactly once. A configured `mg/kg` or `mcg/kg` value is already normalized,
retains its value and unit, and does not require a selected weight. P43's absolute-unit upper
bounds apply only to configured absolute units; all configured units still require a positive,
finite dose.

### Outputs and Pooling

- `fig_B2__paralytic_dose_per_weight_ecdf.csv/.png`: one merged dose per medication in each formed paralytic index.
- `fig_E4__sedation_dose_per_weight_ecdf.csv/.png`: all sedation administration-window pairs in
  the configured +/-5-minute sedation window.
- `step04__combined_induction_dose_distribution_percentiles.csv`: site, etomidate/ketamine drug,
  percentiles 1-99, dose in mg/kg, and contributing pair count.
- `fig_E5__induction_dose_tiers.csv/.png`: local etomidate/ketamine four-tier distribution.
- `fig_E5_2__induction_dose_bins.csv/.png`: local etomidate/ketamine five-bin distribution using
  the same normalized administration-window population as E.5.
- `step04__valid_index_induction_dose_by_stratum.csv`: event-level mg/kg median, Q1, Q3, mean,
  sample SD, available N, and missing-weight N by clinical stratum in the all-valid-index Table 1
  population.
- `fig_E6__valid_index_induction_dose_bins.csv/.png`: five-bin etomidate and ketamine distributions
  after summing repeated administrations per valid index and drug.
- `fig_G1__dose_per_weight_consort.csv/.png`: separate eligibility flows for formed-index
  paralytic medication doses, sedation pairs, and induction-tier pairs. These exclusions do not alter the
  analytic cohort.

The E.5 CSV emits all four tiers for both drugs, including zero cells, with integer numerator and
denominator. Consortium sites concatenate these rows and fit the coordinating center's pooled
logit random-effects model later; a site pipeline does not manufacture pooled estimates or 95%
confidence intervals before all sites are available. Site percentiles must not be averaged. Exact
pooled distributions and percentiles can instead be reconstructed from the integer counts in B.2
and E.4.

E.5 Plot 2 retains that local administration-window denominator and displays five bins. Etomidate
uses `<0.2`, `0.2-0.249`, `0.25-0.299`, `0.3-0.35`, and `>0.35 mg/kg`; ketamine uses `<1`,
`1-1.49`, `1.5-1.99`, `2-2.5`, and `>2.5 mg/kg`. Exact 0.35 and 2.5 values remain in the fourth bins.

Etomidate tiers are `<0.20`, `0.20-<0.25`, `0.25-<0.30`, and `>=0.30 mg/kg`. Ketamine tiers are
`<1.0`, `1.0-<1.5`, `1.5-<2.0`, and `>=2.0 mg/kg`. The induction population is every etomidate or
ketamine administration-window pair in the configured +/-5-minute sedation context, per study-lead direction.
No additional normalized-dose range filter is applied before percentiles or tiers.

The valid-index summary and E.6 are intentionally narrower than E.4/E.5: they require
`imv_transition and any_sedative`, use every qualifying index rather than one index per block, and
sum repeated same-drug administrations within the sedation window. Indexes receiving both drugs
contribute their etomidate component to the etomidate summary and their ketamine component to the
ketamine summary. The published strata are ED/ICU only; on/not-on vasopressor; female/male/other;
Hispanic/non-Hispanic; white/non-white; and SOFA 0-24. Missing and unknown values fold into
not-on, other, non-Hispanic, and non-white, respectively. CCI is not included. E.6 uses etomidate bins `<0.2`,
`0.2-<0.25`, `0.25-<0.3`, `0.3-0.35`, and `>0.35 mg/kg`, and ketamine bins `<1`, `1-<1.5`,
`1.5-<2`, `2-2.5`, and `>2.5 mg/kg`; 0.35 and 2.5 are included in the fourth bin.
