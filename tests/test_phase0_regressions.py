from backend.schemas.jd import JDRequirement, RequirementType
from backend.recommendations.jd import _req_kind


def test_preferred_is_not_required():
    r = JDRequirement(text="Nice to have: Kafka", type=RequirementType.PREFERRED)
    assert _req_kind(r) == "preferred"


def test_required_stays_required():
    r = JDRequirement(text="3+ years Python", type=RequirementType.REQUIRED)
    assert _req_kind(r) == "required"
