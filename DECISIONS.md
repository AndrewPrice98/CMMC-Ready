# Decisions

## Sources and verified facts

Verified 2026-11-09 against primary sources. Where a source disagrees with an
earlier assumption, the source wins and the difference is recorded below.

### DoD Assessment Methodology v1.2.1 (June 24, 2020)

Source: https://www.acq.osd.mil/asda/dpc/cp/cyber/docs/safeguarding/NIST-SP-800-171-Assessment-Methodology-Version-1.2.1-6.24.2020.pdf
(Section 5 and Annex A, read directly from the PDF.)

- Maximum score is 110 ("a contractor is awarded a score of 110"); each requirement not met is subtracted from 110, which "may result in a negative score".
- Deduction values are 5, 3 and 1 (Section 5(d)). 5-point: 23 basic + 19 derived listed in 5(d)(i), plus 3.5.3 and 3.13.11 at their maximum of 5 = 44 requirements. 3-point: 7 basic + 7 derived = 14 requirements. 1-point: all remaining scored derived requirements = 51.
- 3.12.4 (System Security Plan) has Annex A value "NA", so it carries no deduction. Weights therefore total 44x5 + 14x3 + 51x1 = 313, giving a minimum score of 110 - 313 = -203.
- 3.5.3 (MFA), Section 5(e)(i): 3 points subtracted if MFA is implemented only for remote and privileged users; 5 points if not implemented for any users. Annex A value "3 to 5".
- 3.13.11 (FIPS-validated cryptography), Section 5(e)(ii) and 5(i)(iii): 3 points if encryption is employed but not FIPS-validated; 5 points if encryption is not employed. Annex A value "3 to 5".
- Section 5(g): without a system security plan the assessment cannot be completed ("an assessment could not be completed due to incomplete information and noncompliance with DFARS clause 252.204-7012"). A plan of action is not a substitute for a completed requirement.
- Basic (self) assessment confidence is "Low"; summary score is posted to SPRS.

### 32 CFR 170 (CMMC Program final rule)

- Effective date December 16, 2024; 89 FR 83092 (Oct. 15, 2024). DATES section: "This rule is effective December 16, 2024." https://www.govinfo.gov/content/pkg/FR-2024-10-15/html/2024-22905.htm . The eCFR version history lists 170.21 as issued 2024-12-16: https://www.ecfr.gov/api/versioner/v1/versions/title-32.json?part=170&section=170.21
- 32 CFR 170.21 (POA&M rules), text at https://www.ecfr.gov/api/versioner/v1/full/2025-01-01/title-32.xml?part=170&section=170.21 :
  - Level 2 conditional status requires assessment score divided by the number of Level 2 requirements to be at least 0.8; with 110 requirements that is 88. (The CFR states the 0.8 ratio, not the number 88; 88 is derived.)
  - No requirement with a point value greater than 1 may be on the POA&M, except SC.L2-3.13.11, which may be included if encryption is used but not FIPS-validated (point value 3).
  - Closeout assessment must confirm closure within 180 days of the Conditional CMMC Status Date, otherwise conditional status expires.
  - Additionally (see D1): AC.L2-3.1.20, AC.L2-3.1.22, CA.L2-3.12.4, PE.L2-3.10.3, PE.L2-3.10.4 and PE.L2-3.10.5 may not be on the POA&M.

### 48 CFR (DFARS) CMMC acquisition rule

- Final rule published September 10, 2025, 90 FR 43560 (DFARS Case 2019-D041); DATES: "This rule is effective November 10, 2025." Phase 1 (Level 1 and Level 2 self-assessments in applicable solicitations) begins on that date. https://www.govinfo.gov/content/pkg/FR-2025-09-10/html/2025-17359.htm
- Phase dates are set by 32 CFR 170.3(e) (https://www.ecfr.gov/api/versioner/v1/full/2025-01-01/title-32.xml?part=170&section=170.3, verified 2026-11-10): Phase 1 begins on the effective date of the DFARS rule; Phase 2 "begins one calendar year following the start date of Phase 1"; Phase 3 one calendar year after Phase 2; Phase 4 one calendar year after Phase 3. With Phase 1 starting November 10, 2025, Phase 2 begins November 10, 2026 (DoD intends to require Level 2 (C3PAO) status in applicable solicitations from then), Phase 3 November 10, 2027 and Phase 4 November 10, 2028. No scoring constant depends on them.

### NIST SP 800-171 Rev 2

- Source: https://csrc.nist.gov/pubs/sp/800/171/r2/upd1/final (February 2020, includes updates as of January 28, 2021). The PDF is the authoritative text. The page notes Rev 2 was withdrawn May 14, 2024 and superseded by Rev 3. CMMC Level 2 is still defined against Rev 2: 32 CFR 170.2(a)(9) incorporates by reference "SP 800-171, ... Revision 2, February 2020 (includes updates as of January 28, 2021), (NIST SP 800-171 R2)", IBR approved for 170.4(b) and 170.14(a) through (c) (verified 2026-11-10 at https://www.ecfr.gov/api/versioner/v1/full/2025-01-01/title-32.xml?part=170&section=170.2). That is why Rev 3 is out of scope.
- Requirement counts per family, confirmed against the numbering in the DoD methodology Annex A: AC 22, AT 3, AU 9, CM 9, IA 11, IR 3, MA 6, MP 9, PS 2, PE 6, RA 3, CA 4, SC 16, SI 7 = 110.
- SP 800-171A (June 2018, https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171a.pdf) has 320 assessment objectives: 297 lettered objectives plus 23 requirements with a single, unlettered objective. NIST's CPRT JSON export and the 800-171A CSV also contain 320 (verified 2026-11-09).
- The Basic requirements in the Rev 2 CSV (31) are exactly the 30 Basic requirements in the methodology's 5-point and 3-point lists (Section 5(d)) plus 3.12.4.

### Control catalog

Built by `backend/scripts/build_catalog.py` into `backend/data/nist_800_171r2.json`; source files were retrieved 2026-11-09 and the URLs are recorded in the JSON `source` field.

- Requirement text, discussion and footnotes come from NIST's Rev 2 CSV (https://csrc.nist.gov/files/pubs/sp/800/171/r2/upd1/final/docs/sp800-171r2-security-reqs.csv). Compared word by word with the Rev 2 PDF, it differs only in closing periods in 19 places (10 requirement statements, 9 discussions) and one word (3.1.16 discussion: the PDF says "[SP 800-97] provide guidance"). The PDF wording is used; the script asserts each correction.
- Objectives come from the SP 800-171A PDF, not from NIST's 800-171A CSV or the CPRT export. Both machine-readable files carry a different wording for 33 of the 320 objectives (for example 3.1.4[b] and [c] are different statements, 3.1.17[a] and [b] are swapped, and 3.11.2[a] to [e] use the pre-publication scope). The PDF is the published text.
- An unlettered single objective (for example 3.14.4) is given the ID `[a]` so that every objective ID has the form `<requirement>[<letter>]`. The leading "Determine if" is not stored.
- Rev 2 footnotes are kept in a `footnotes` list on the requirement that references them (3.1.19, 3.5.3, 3.7.1, 3.8.4, 3.12.4, 3.13.12), because the CSV attaches some of them to the wrong row (the 3.12.4 SSP footnote sits in the 3.13.1 row).
- Weights are transcribed from Annex A and match the Section 5(d) lists for all 110 requirements: 44 at 5 (including 3.5.3 and 3.13.11 at their maximum), 14 at 3, 51 at 1, and 3.12.4 at 0 ("NA"). Partial values: 3.5.3 `mfa_remote_privileged_only` 3, 3.13.11 `encryption_not_fips` 3.
- `poam_allowed` is true for weight-1 requirements except the six in D1, and true for 3.13.11 meaning "may be eligible": scoring must still require it to be at the 3-point partial.
- D3: NIST's CPRT export and the 800-171A CSV are not reliable sources for objective wording (see above). They were used only as a cross-check.

### Facts not independently verified

- The 7 organization-defined parameter defaults (minimum password length 12 characters, lockout after 10 failed attempts, session lock after 15 minutes, password history of 24, audit log retention of 90 days, maximum patch age of 35 days, maximum sign-in frequency of 12 hours) are project design choices, not source facts. They are defaults the assessor can change per assessment.
- Federal Register website pages blocked automated access; govinfo.gov copies of the same documents were used instead.

### Discrepancies between early assumptions and sources

- D1: It is easy to assume a POA&M may hold only weight-1 requirements plus 3.13.11 at -3. 32 CFR 170.21 also bars six specific requirements from the POA&M even though they are weight 1: 3.1.20, 3.1.22, 3.12.4, 3.10.3, 3.10.4, 3.10.5. The catalog therefore carries an explicit exclusion list.
- D2: It is easy to assume every weight is in {1, 3, 5}. The methodology gives 3.12.4 a value of "NA" (not scored). Total 313 only holds if 3.12.4 contributes 0; with it at 1 the total would be 314. Weights also include the 3.5.3 and 3.13.11 maxima of 5 with partial values of 3.

## Deployment, documentation and CI

- The README's "Why CMMC matters now" uses only the dates verified above (32 CFR 170 effective December 16, 2024; the DFARS rule effective November 10, 2025, starting Phase 1; Phase 2 one calendar year later under 32 CFR 170.3(e)).
- `python -m cmmcready demo` loads the fixture into its own file, `backend/data/demo.db` (git-ignored), never into `CMMCREADY_DB`; `--reset` deletes and reloads it, `--serve` then runs uvicorn on it with `CMMCREADY_DEMO=true`. `serve` runs the API on the configured database.
- The collector coverage table is generated from `rules.yml` (`backend/cmmcready/coverage.py`). The full table is `docs/COLLECTOR_COVERAGE.md`; a per-family summary sits in the README between `coverage:start` / `coverage:end` markers. `catalog --coverage-md --check` (CI and a test) fails when either is stale. What a rule "may record" is derived from its definition: `met_result`, `unmet_if`/`fail_result`, and `info`.
- Packaging: the app is run from `backend/` and never pip-installed, so `pyproject.toml` declares no package data. The Vercel function gets `rules.yml` and `backend/data/*.json` through `includeFiles` (`{backend/cmmcready/**,backend/data/**}`); `test_vercel_entry.py` checks that every file the API reads is matched by it and not excluded by `.vercelignore`, and that the root `requirements.txt` equals the backend runtime dependencies minus uvicorn.
- The interface adds two bundled packages, `@fontsource-variable/inter` (the typeface, self-hosted so the Content Security Policy stays at `default-src 'self'`) and `lucide-react` (icons); licences are in THIRD_PARTY.md. Screenshots are taken from the guest view of the demo at 1400 px wide with Playwright (not a project dependency).
- Accepted advisories: 2 moderate npm advisories in react-router 6.x (GHSA-wrjc-x8rr-h8h6, GHSA-337j-9hxr-rhxg). The fix is react-router v7, outside the pinned stack; the second concerns SSR hydration, which this client-only app does not use. CI fails only on high severity.

## Licence position

NIST and DoD publications are works of the U.S. Government and the text may be included with attribution. NIST SP 800-171 Rev 2, SP 800-171A and the DoD Assessment Methodology are cited by title, version, URL and retrieval date in the `source` field of `backend/data/nist_800_171r2.json`. No third-party commentary is copied. The code is MIT-licensed (LICENSE, standard text so GitHub detects it); the README notes that the NIST and DoD text are U.S. Government works.
