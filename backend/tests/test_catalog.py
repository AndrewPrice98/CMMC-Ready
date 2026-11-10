import copy
import dataclasses
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from cmmcready.catalog import Catalog, load_catalog, validate

BACKEND = Path(__file__).resolve().parent.parent

FAMILY_COUNTS = {
    "AC": 22, "AT": 3, "AU": 9, "CM": 9, "IA": 11, "IR": 3, "MA": 6,
    "MP": 9, "PS": 2, "PE": 6, "RA": 3, "CA": 4, "SC": 16, "SI": 7,
}

# 32 CFR 170.21(a)(2)(iii): weight-1 requirements that may not be on a POA&M.
POAM_EXCLUDED = {"3.1.20", "3.1.22", "3.10.3", "3.10.4", "3.10.5", "3.12.4"}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def _key(req_id):
    return tuple(int(part) for part in req_id.split("."))


def test_counts(catalog):
    assert len(catalog.requirements) == 110
    assert sum(len(r.objectives) for r in catalog.requirements) == 320
    assert Counter(r.family for r in catalog.requirements) == FAMILY_COUNTS
    assert [f.code for f in catalog.families()] == list(FAMILY_COUNTS)
    assert sum(r.basic for r in catalog.requirements) == 31


def test_weights(catalog):
    weights = {r.id: r.weight for r in catalog.requirements}
    assert sum(weights.values()) == 313
    assert weights["3.12.4"] == 0
    assert all(w in {1, 3, 5} for rid, w in weights.items() if rid != "3.12.4")
    assert Counter(w for rid, w in weights.items() if rid != "3.12.4") == {5: 44, 3: 14, 1: 51}
    assert catalog.by_id("3.5.3").weight == 5
    assert catalog.by_id("3.5.3").partial == {"mfa_remote_privileged_only": 3}
    assert catalog.by_id("3.13.11").weight == 5
    assert catalog.by_id("3.13.11").partial == {"encryption_not_fips": 3}
    assert [r.id for r in catalog.requirements if r.partial] == ["3.5.3", "3.13.11"]


def test_poam_exclusions(catalog):
    allowed = {r.id for r in catalog.requirements if r.poam_allowed}
    weight_one = {r.id for r in catalog.requirements if r.weight == 1}
    assert allowed == (weight_one - POAM_EXCLUDED) | {"3.13.11"}
    for rid in POAM_EXCLUDED:
        assert catalog.by_id(rid).poam_allowed is False
    assert catalog.by_id("3.13.11").poam_allowed is True
    assert catalog.by_id("3.5.3").poam_allowed is False


def test_ids_unique_and_ordered(catalog):
    ids = [r.id for r in catalog.requirements]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids, key=_key)
    obj_ids = [o.id for r in catalog.requirements for o in r.objectives]
    assert len(obj_ids) == len(set(obj_ids))
    for r in catalog.requirements:
        assert r.id.startswith(r.family_number + ".")
        letters = [o.id[len(r.id):] for o in r.objectives]
        expected = [f"[{chr(ord('a') + i)}]" for i in range(len(letters))]
        assert letters == expected, r.id


def test_every_requirement_has_objectives(catalog):
    for r in catalog.requirements:
        assert r.objectives, r.id
        assert r.text and r.discussion, r.id
        for o in r.objectives:
            assert o.text.strip() == o.text and o.text, o.id


def test_text_is_clean(catalog):
    marker = re.compile(r"\[\d+\]|�|\t|  ")
    for r in catalog.requirements:
        assert not marker.search(r.text), r.id
        assert r.text.endswith("."), r.id
        for para in r.discussion.split("\n\n"):
            assert para and not marker.search(para) and "\n" not in para, r.id
        for o in r.objectives:
            assert not marker.search(o.text), o.id


def test_verbatim_spot_checks(catalog):
    r = catalog.by_id("3.5.3")
    assert r.text == (
        "Use multifactor authentication for local and network access to privileged "
        "accounts and for network access to non-privileged accounts."
    )
    assert r.family == "IA" and r.family_name == "Identification and Authentication"
    assert r.basic is False
    assert [o.text for o in r.objectives] == [
        "privileged accounts are identified.",
        "multifactor authentication is implemented for local access to privileged accounts.",
        "multifactor authentication is implemented for network access to privileged accounts.",
        "multifactor authentication is implemented for network access to non-privileged accounts.",
    ]
    assert r.footnotes[0].startswith("Multifactor authentication requires two or more different factors")
    assert catalog.by_id("3.1.1").objectives[0].id == "3.1.1[a]"
    assert catalog.by_id("3.1.1").objectives[0].text == "authorized users are identified."
    single = catalog.by_id("3.14.4").objectives
    assert [(o.id, o.text) for o in single] == [
        ("3.14.4[a]", "malicious code protection mechanisms are updated when new releases are available.")
    ]
    assert len(catalog.by_id("3.1.22").objectives) == 5
    assert catalog.by_id("3.12.4").objectives[-1].id == "3.12.4[h]"
    assert catalog.by_id("3.12.4").footnotes[0].startswith("There is no prescribed format")
    assert not catalog.by_id("3.13.1").footnotes


def test_by_id_unknown_raises(catalog):
    with pytest.raises(KeyError):
        catalog.by_id("3.99.1")


def test_source_recorded(catalog):
    urls = " ".join(d["url"] for d in catalog.source["documents"])
    assert "sp800-171r2-security-reqs.csv" in urls
    assert "NIST.SP.800-171a.pdf" in urls
    assert "Assessment-Methodology-Version-1.2.1" in urls
    assert catalog.source["retrieved"] == "2026-11-09"


def test_validate_passes_and_catches_bad_data(catalog):
    assert validate(catalog) == []
    bad_reqs = copy.deepcopy(catalog.requirements)
    bad_reqs[0] = dataclasses.replace(bad_reqs[0], weight=3)
    bad_reqs[1] = dataclasses.replace(bad_reqs[1], objectives=[])
    problems = validate(Catalog(requirements=bad_reqs, source=catalog.source))
    assert any("total weight" in p for p in problems)
    assert any("3.1.2" in p and "objectives" in p for p in problems)


def test_check_cli():
    result = subprocess.run(
        [sys.executable, "-m", "cmmcready", "catalog", "--check"],
        cwd=BACKEND, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "110 requirements, 320 objectives, total weight 313"
