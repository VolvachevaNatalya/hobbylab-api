"""
Regression tests for GET /classes/search age-range filtering.

New parameters:
  min_age  — lower bound of the requested age range (inclusive)
  max_age  — upper bound of the requested age range (inclusive)

A class is returned when at least one of its groups has an age range that
overlaps the requested range.  Interval [age_from, age_to] overlaps
[min_age, max_age] iff:
    age_from <= max_age  AND  age_to >= min_age

The existing `age` point-filter is preserved unchanged for backward compat.
"""
import pytest

from app.core.security import create_access_token, hash_password
from app.models.category import Category
from app.models.classes import Class
from app.models.group import Group
from app.models.organization import Organization
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email):
    u = User(email=email, name="T", password_hash=hash_password("pw"), status="active")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name="Org"):
    cat = Category(name=f"Cat-{name}")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    o = Organization(name=name, status="active", verified=True)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o, cat


def _make_class(db, org_id, cat_id, name):
    c = Class(organization_id=org_id, category_id=cat_id, name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_group(db, class_id, age_from, age_to, name="Group"):
    g = Group(class_id=class_id, name=name, age_from=age_from, age_to=age_to)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


def _search(client, user_id, **params):
    return client.get(
        "/classes/search",
        params={k: v for k, v in params.items() if v is not None},
        headers=_auth(user_id),
    )


def _class_names(response):
    return {item["class"]["name"] for item in response.json()["items"]}


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _setup(db):
    """
    Four classes with group age ranges:
      A — [3,  6]  toddlers/early kids
      B — [7, 12]  school age
      C — [13, 18] teens
      D — [5, 15]  wide cross-cutting range
    Returns (user, class_a, class_b, class_c, class_d).
    """
    user = _make_user(db, "age_range_user@test.com")
    org, cat = _make_org(db, "AgeOrg")

    cls_a = _make_class(db, org.id, cat.id, "Toddlers")
    _make_group(db, cls_a.id, age_from=3, age_to=6)

    cls_b = _make_class(db, org.id, cat.id, "SchoolAge")
    _make_group(db, cls_b.id, age_from=7, age_to=12)

    cls_c = _make_class(db, org.id, cat.id, "Teens")
    _make_group(db, cls_c.id, age_from=13, age_to=18)

    cls_d = _make_class(db, org.id, cat.id, "WideRange")
    _make_group(db, cls_d.id, age_from=5, age_to=15)

    return user, cls_a, cls_b, cls_c, cls_d


# ═══════════════════════════════════════════════════════════════════════════════
# Overlap — both min_age and max_age supplied
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgeRangeOverlap:

    def test_range_mid_overlaps_ab_and_d(self, client, db):
        """
        [4, 8] overlaps A [3,6] (at 4-6), B [7,12] (at 7-8), D [5,15] (at 5-8).
        C [13,18] does not overlap.
        """
        user, _, _, cls_c, _ = _setup(db)
        resp = _search(client, user.id, min_age=4, max_age=8)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "Toddlers" in names
        assert "SchoolAge" in names
        assert "WideRange" in names
        assert "Teens" not in names

    def test_range_high_overlaps_cd_and_d(self, client, db):
        """
        [11, 14] overlaps B [7,12] (at 11-12), C [13,18] (at 13-14), D [5,15] (at 11-14).
        A [3,6] does not overlap.
        """
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, min_age=11, max_age=14)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "SchoolAge" in names
        assert "Teens" in names
        assert "WideRange" in names
        assert "Toddlers" not in names

    def test_range_covers_all(self, client, db):
        """[1, 20] is a superset of every group range — all four classes returned."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, min_age=1, max_age=20)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert {"Toddlers", "SchoolAge", "Teens", "WideRange"}.issubset(names)

    def test_range_matches_nothing(self, client, db):
        """[20, 25] is above every group ceiling — no classes returned."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, min_age=20, max_age=25)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "Toddlers" not in names
        assert "SchoolAge" not in names
        assert "Teens" not in names
        assert "WideRange" not in names

    def test_point_range_same_as_age_param(self, client, db):
        """min_age=7, max_age=7 is equivalent to age=7 (matches B and D)."""
        user, _, _, _, _ = _setup(db)
        resp_range = _search(client, user.id, min_age=7, max_age=7)
        resp_age = _search(client, user.id, age=7)
        assert resp_range.status_code == 200
        assert resp_age.status_code == 200
        assert _class_names(resp_range) == _class_names(resp_age)


# ═══════════════════════════════════════════════════════════════════════════════
# Boundary ages
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgeRangeBoundaries:

    def test_exact_boundary_between_a_and_b(self, client, db):
        """
        [6, 7] touches the top of A [3,6] and the bottom of B [7,12].
        Both must be returned (boundary is inclusive).
        """
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, min_age=6, max_age=7)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "Toddlers" in names   # A touches at 6
        assert "SchoolAge" in names  # B touches at 7
        assert "WideRange" in names  # D overlaps 6-7

    def test_max_equal_to_group_lower_bound(self, client, db):
        """max_age=7 must include B [7,12] because age_from(7) <= max_age(7)."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, min_age=5, max_age=7)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "SchoolAge" in names

    def test_min_equal_to_group_upper_bound(self, client, db):
        """min_age=12 must include B [7,12] because age_to(12) >= min_age(12)."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, min_age=12, max_age=15)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "SchoolAge" in names

    def test_just_outside_boundary_excludes_class(self, client, db):
        """[13, 20] excludes B [7,12] because 12 < min_age(13)."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, min_age=13, max_age=20)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "SchoolAge" not in names


# ═══════════════════════════════════════════════════════════════════════════════
# Open-ended ranges (only one bound supplied)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgeRangeOpenEnded:

    def test_min_age_only_excludes_classes_capped_below(self, client, db):
        """
        min_age=14 → age_to >= 14.
        A(6) and B(12) don't qualify; C(18) and D(15) do.
        """
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, min_age=14)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "Toddlers" not in names
        assert "SchoolAge" not in names
        assert "Teens" in names
        assert "WideRange" in names

    def test_max_age_only_excludes_classes_starting_above(self, client, db):
        """
        max_age=4 → age_from <= 4.
        Only A [3,6] qualifies; B, C, D all start above 4.
        """
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, max_age=4)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "Toddlers" in names
        assert "SchoolAge" not in names
        assert "Teens" not in names
        assert "WideRange" not in names

    def test_min_age_zero_matches_all(self, client, db):
        """min_age=0 → age_to >= 0, satisfied by any group with a non-negative upper bound."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, min_age=0)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert {"Toddlers", "SchoolAge", "Teens", "WideRange"}.issubset(names)


# ═══════════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgeRangeValidation:

    def test_min_greater_than_max_returns_422(self, client, db):
        user = _make_user(db, "age_val@test.com")
        resp = _search(client, user.id, min_age=10, max_age=5)
        assert resp.status_code == 422

    def test_min_equals_max_is_valid(self, client, db):
        """A single-age point query (min=max) is always valid."""
        user = _make_user(db, "age_eq@test.com")
        resp = _search(client, user.id, min_age=8, max_age=8)
        assert resp.status_code == 200

    def test_no_age_params_returns_all_classes(self, client, db):
        """When no age filter is provided, all classes are returned regardless of group ranges."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert {"Toddlers", "SchoolAge", "Teens", "WideRange"}.issubset(names)


# ═══════════════════════════════════════════════════════════════════════════════
# Backward compatibility — existing `age` parameter
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgeBackwardCompat:

    def test_age_point_filter_unchanged(self, client, db):
        """
        age=10 uses the original logic: age_from<=10 AND age_to>=10.
        Matches B [7,12] and D [5,15]; excludes A [3,6] and C [13,18].
        """
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, age=10)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "SchoolAge" in names
        assert "WideRange" in names
        assert "Toddlers" not in names
        assert "Teens" not in names

    def test_age_at_lower_boundary(self, client, db):
        """age=7 matches classes whose groups start at exactly 7."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, age=7)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "SchoolAge" in names
        assert "WideRange" in names

    def test_age_at_upper_boundary(self, client, db):
        """age=12 matches classes whose groups end at exactly 12."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, age=12)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "SchoolAge" in names
        assert "WideRange" in names

    def test_age_outside_all_ranges_returns_nothing(self, client, db):
        """age=25 matches no group — no classes returned."""
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, age=25)
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_age_and_range_params_independent(self, client, db):
        """
        When both `age` and range params are provided both constraints apply.
        age=10 AND min_age=12, max_age=16 — no group satisfies both simultaneously.
        age=10 requires age_from<=10 AND age_to>=10;
        min_age=12 additionally requires age_to>=12.
        B [7,12]: age_to(12) >= 12 ✓, age_from(7) <= 10 ✓, age_to(12) >= 10 ✓ → matches.
        D [5,15]: all conditions met → matches.
        But max_age=12 AND age=10:
          D [5,15]: age_from(5)<=12 ✓, age_to(15)>=10 ✓ → matches.
        Let's use a simple non-conflicting check: age=5 AND max_age=4.
        age=5 requires age_to>=5; max_age=4 requires age_from<=4.
        A [3,6]: age_to(6)>=5 ✓, age_from(3)<=4 ✓ → matches.
        B [7,12]: age_to>=5 ✓ but age_from(7)<=4? No → excluded.
        """
        user, _, _, _, _ = _setup(db)
        resp = _search(client, user.id, age=5, max_age=4)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "Toddlers" in names
        assert "SchoolAge" not in names
        assert "Teens" not in names

    def test_existing_search_params_still_work_with_age_range(self, client, db):
        """
        Adding min_age/max_age doesn't break other filters.
        category_id filter combined with age range works correctly.
        """
        user = _make_user(db, "combo_user@test.com")
        org, cat = _make_org(db, "ComboOrg")
        cat2 = Category(name="OtherCat")
        db.add(cat2)
        db.commit()
        db.refresh(cat2)

        cls_in = _make_class(db, org.id, cat.id, "InCategory")
        _make_group(db, cls_in.id, age_from=5, age_to=10)

        cls_out = _make_class(db, org.id, cat2.id, "OtherCategory")
        _make_group(db, cls_out.id, age_from=5, age_to=10)

        resp = _search(client, user.id, min_age=5, max_age=10, category_id=cat.id)
        assert resp.status_code == 200
        names = _class_names(resp)
        assert "InCategory" in names
        assert "OtherCategory" not in names
