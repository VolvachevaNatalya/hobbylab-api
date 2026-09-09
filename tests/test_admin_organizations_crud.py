"""Tests for POST/PATCH/DELETE /admin/organizations."""
from datetime import datetime

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.organization import Organization
from app.models.organization_category import OrganizationCategory
from app.models.organization_user import OrganizationUser
from app.models.user import User

_EXPECTED_ORG_RESPONSE_FIELDS = {
    "id", "name", "description", "logo_url", "banner_url",
    "email", "phone", "website",
    "instagram_url", "facebook_url", "telegram_url", "youtube_url",
    "tiktok_url", "whatsapp_url",
    "address", "city", "city_id", "latitude", "longitude",
    "trial_lesson_available", "trial_lesson_price", "trial_lesson_comment",
    "status", "verified", "created_at", "updated_at",
    "users", "categories",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False, name="Test User"):
    u = User(email=email, name=name, password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name="Org", status="active", verified=False):
    o = Organization(name=name, status=status, verified=verified)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_category(db, name="Cat"):
    c = Category(name=name, name_en=name, name_ru=name, name_he=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_org_user(db, org_id, user_id, role="owner"):
    ou = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(ou)
    db.commit()
    return ou


def _make_event(db, org_id, title="Event"):
    e = Event(
        organization_id=org_id,
        title=title,
        start_datetime=datetime(2099, 1, 1, 10, 0, 0),
        status="active",
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/organizations
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_org_create_200_for_system_admin(client, db):
    admin = _make_user(db, "cr_adm@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "NewOrg", "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_org_create_403_for_normal_user(client, db):
    user = _make_user(db, "cr_usr@x.com")
    resp = client.post("/admin/organizations",
                       json={"name": "Forbidden"},
                       headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_org_create_401_for_unauthenticated(client, db):
    resp = client.post("/admin/organizations", json={"name": "Anon"})
    assert resp.status_code == 401


def test_admin_org_create_requires_name(client, db):
    admin = _make_user(db, "cr_req@x.com", is_system_admin=True)
    resp = client.post("/admin/organizations",
                       json={"description": "Missing name"},
                       headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_org_create_without_category_ids_returns_422(client, db):
    """category_ids is required — omitting it returns 422 (matches mobile behavior)."""
    admin = _make_user(db, "cr_nocat@x.com", is_system_admin=True)
    resp = client.post("/admin/organizations",
                       json={"name": "NoCatOrg"},
                       headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_org_create_empty_category_ids_returns_422(client, db):
    """category_ids=[] is rejected — at least one category is required."""
    admin = _make_user(db, "cr_emptycat@x.com", is_system_admin=True)
    resp = client.post("/admin/organizations",
                       json={"name": "EmptyCatOrg", "category_ids": []},
                       headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_org_create_response_fields(client, db):
    admin = _make_user(db, "cr_fld@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "FieldOrg", "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == _EXPECTED_ORG_RESPONSE_FIELDS
    assert data["name"] == "FieldOrg"
    assert isinstance(data["id"], int)


def test_admin_org_create_persists_to_db(client, db):
    admin = _make_user(db, "cr_db@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "PersistOrg", "email": "org@example.com",
                             "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    org_id = resp.json()["id"]
    row = db.query(Organization).filter(Organization.id == org_id).first()
    assert row is not None
    assert row.name == "PersistOrg"
    assert row.email == "org@example.com"


def test_admin_org_create_default_status_is_pending(client, db):
    admin = _make_user(db, "cr_st@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "PendingOrg", "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.json()["status"] == "pending"


def test_admin_org_create_custom_status_active(client, db):
    admin = _make_user(db, "cr_act@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "ActiveOrg", "status": "active",
                             "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_admin_org_create_invalid_status_returns_422(client, db):
    admin = _make_user(db, "cr_inv@x.com", is_system_admin=True)
    resp = client.post("/admin/organizations",
                       json={"name": "BadOrg", "status": "deleted"},
                       headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_org_create_default_verified_false(client, db):
    admin = _make_user(db, "cr_vf@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "UnverifiedOrg", "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.json()["verified"] is False


def test_admin_org_create_verified_true(client, db):
    admin = _make_user(db, "cr_vt@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "VerifiedOrg", "verified": True,
                             "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["verified"] is True


def test_admin_org_create_with_owner_creates_org_user(client, db):
    admin = _make_user(db, "cr_oadm@x.com", is_system_admin=True)
    owner = _make_user(db, "cr_own@x.com", name="The Owner")
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "OwnedOrg", "owner_id": owner.id,
                             "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["users"]) == 1
    u = data["users"][0]
    assert u["id"] == owner.id
    assert u["role"] == "owner"
    # Verify in DB
    ou = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == data["id"],
        OrganizationUser.user_id == owner.id,
    ).first()
    assert ou is not None
    assert ou.role == "owner"


def test_admin_org_create_without_owner_no_org_user(client, db):
    admin = _make_user(db, "cr_noadm@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "OwnerlessOrg", "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["users"] == []
    ou_count = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == data["id"]
    ).count()
    assert ou_count == 0


def test_admin_org_create_invalid_owner_id_returns_400(client, db):
    admin = _make_user(db, "cr_badow@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "BadOwnerOrg", "owner_id": 999999,
                             "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 400


def test_admin_org_create_system_admin_never_assigned_as_owner(client, db):
    """System admin must never be silently added as org owner when owner_id is omitted."""
    admin = _make_user(db, "cr_noslnt@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "SilentOwnerGuardOrg", "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    org_id = resp.json()["id"]

    # The admin's own user_id must not appear in organization_users for this org
    admin_as_member = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org_id,
        OrganizationUser.user_id == admin.id,
    ).first()
    assert admin_as_member is None


def test_admin_org_create_with_categories(client, db):
    admin = _make_user(db, "cr_cat@x.com", is_system_admin=True)
    cat = _make_category(db, "Dance")
    resp = client.post("/admin/organizations",
                       json={"name": "CatOrg", "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["categories"]) == 1
    assert data["categories"][0]["id"] == cat.id


def test_admin_org_create_id_not_supplied_by_client(client, db):
    admin = _make_user(db, "cr_noid@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "NoIdOrg", "id": 99999,
                             "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["id"] != 99999


def test_admin_org_create_contact_fields_preserved(client, db):
    admin = _make_user(db, "cr_cont@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={
                           "name": "ContactOrg",
                           "email": "contact@org.com",
                           "phone": "+972501234567",
                           "website": "https://org.com",
                           "instagram_url": "https://instagram.com/org",
                           "category_ids": [cat.id],
                       },
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "contact@org.com"
    assert data["phone"] == "+972501234567"
    assert data["website"] == "https://org.com"
    assert data["instagram_url"] == "https://instagram.com/org"


def test_admin_org_create_valid_email_accepted(client, db):
    admin = _make_user(db, "cr_em_ok@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "EmailOrg", "email": "valid@example.com",
                             "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["email"] == "valid@example.com"


def test_admin_org_create_malformed_email_accepted(client, db):
    # Organization.email is Optional[str] — the mobile API applies no format
    # validation. Admin must match that behavior; malformed values are stored
    # as-is (format enforcement is a future product decision).
    admin = _make_user(db, "cr_em_bad@x.com", is_system_admin=True)
    cat = _make_category(db, "Cat")
    resp = client.post("/admin/organizations",
                       json={"name": "MalformedEmailOrg", "email": "not-an-email",
                             "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["email"] == "not-an-email"


def test_admin_org_patch_valid_email_accepted(client, db):
    admin = _make_user(db, "pa_em_ok@x.com", is_system_admin=True)
    org = _make_org(db, name="PatchEmailOrg")
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"email": "updated@example.com"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["email"] == "updated@example.com"


def test_admin_org_patch_malformed_email_accepted(client, db):
    # Matches mobile PATCH behavior — no format validation on organization email.
    admin = _make_user(db, "pa_em_bad@x.com", is_system_admin=True)
    org = _make_org(db, name="PatchMalformedEmailOrg")
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"email": "not-an-email"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["email"] == "not-an-email"


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/organizations/{organization_id}
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_org_get_200_for_system_admin(client, db):
    admin = _make_user(db, "get_adm@x.com", is_system_admin=True)
    org = _make_org(db, name="GetOrg")
    resp = client.get(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_org_get_403_for_normal_user(client, db):
    user = _make_user(db, "get_usr@x.com")
    org = _make_org(db, name="ForbidGet")
    resp = client.get(f"/admin/organizations/{org.id}", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_org_get_401_for_unauthenticated(client, db):
    org = _make_org(db, name="AnonGet")
    resp = client.get(f"/admin/organizations/{org.id}")
    assert resp.status_code == 401


def test_admin_org_get_404_for_missing_org(client, db):
    admin = _make_user(db, "get_404@x.com", is_system_admin=True)
    resp = client.get("/admin/organizations/999999", headers=_auth(admin.id))
    assert resp.status_code == 404


def test_admin_org_get_full_fields_returned(client, db):
    admin = _make_user(db, "get_fld@x.com", is_system_admin=True)
    org = _make_org(db, name="FullGetOrg")
    resp = client.get(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert set(resp.json().keys()) == _EXPECTED_ORG_RESPONSE_FIELDS


def test_admin_org_get_categories_returned(client, db):
    admin = _make_user(db, "get_cat@x.com", is_system_admin=True)
    cat = _make_category(db, "GetCat")
    org = _make_org(db, name="CatGetOrg")
    db.add(OrganizationCategory(organization_id=org.id, category_id=cat.id, position=0))
    db.commit()
    resp = client.get(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    cats = resp.json()["categories"]
    assert len(cats) == 1
    assert cats[0]["id"] == cat.id


def test_admin_org_get_users_and_roles_returned(client, db):
    admin = _make_user(db, "get_usr_adm@x.com", is_system_admin=True)
    owner = _make_user(db, "get_owner@x.com", name="OrgOwner")
    org = _make_org(db, name="UsersGetOrg")
    _make_org_user(db, org.id, owner.id, role="owner")
    resp = client.get(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert len(users) == 1
    assert users[0]["id"] == owner.id
    assert users[0]["role"] == "owner"
    assert users[0]["email"] == "get_owner@x.com"


def test_admin_org_get_city_id_preserved(client, db):
    from app.models.city import City as CityModel
    admin = _make_user(db, "get_city@x.com", is_system_admin=True)
    city = CityModel(name_he="תל אביב", name_en="Tel Aviv", name_ru="Тель-Авив", is_active=True)
    db.add(city)
    db.commit()
    db.refresh(city)
    org = _make_org(db, name="CityGetOrg")
    org.city_id = city.id
    org.city = "Tel Aviv"
    db.commit()
    resp = client.get(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["city_id"] == city.id
    assert data["city"] == "Tel Aviv"


def test_admin_org_get_trial_lesson_values_preserved(client, db):
    admin = _make_user(db, "get_trl@x.com", is_system_admin=True)
    org = _make_org(db, name="TrialGetOrg")
    org.trial_lesson_available = True
    org.trial_lesson_price = 50.0
    org.trial_lesson_comment = "First lesson free"
    db.commit()
    resp = client.get(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["trial_lesson_available"] is True
    assert data["trial_lesson_price"] == 50.0
    assert data["trial_lesson_comment"] == "First lesson free"


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /admin/organizations/{organization_id}
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_org_patch_200_for_system_admin(client, db):
    admin = _make_user(db, "pa_adm@x.com", is_system_admin=True)
    org = _make_org(db, name="PatchOrg")
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"name": "PatchedOrg"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_org_patch_403_for_normal_user(client, db):
    user = _make_user(db, "pa_usr@x.com")
    org = _make_org(db, name="ForbidPatch")
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"name": "Nope"},
                        headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_org_patch_401_for_unauthenticated(client, db):
    org = _make_org(db, name="AnonPatch")
    resp = client.patch(f"/admin/organizations/{org.id}", json={"name": "Nope"})
    assert resp.status_code == 401


def test_admin_org_patch_404_for_missing_org(client, db):
    admin = _make_user(db, "pa_404@x.com", is_system_admin=True)
    resp = client.patch("/admin/organizations/999999",
                        json={"name": "Ghost"},
                        headers=_auth(admin.id))
    assert resp.status_code == 404


def test_admin_org_patch_partial_update_preserves_other_fields(client, db):
    admin = _make_user(db, "pa_part@x.com", is_system_admin=True)
    org = _make_org(db, name="FullOrg")
    # Manually set many fields
    org.email = "orig@org.com"
    org.phone = "+1234"
    org.description = "Original description"
    org.status = "active"
    db.commit()

    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"name": "OnlyNameChanged"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "OnlyNameChanged"
    assert data["email"] == "orig@org.com"       # unchanged
    assert data["phone"] == "+1234"              # unchanged
    assert data["description"] == "Original description"  # unchanged
    assert data["status"] == "active"            # unchanged


def test_admin_org_patch_null_name_returns_422(client, db):
    admin = _make_user(db, "pa_nname@x.com", is_system_admin=True)
    org = _make_org(db, name="NameGuardOrg")
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"name": None},
                        headers=_auth(admin.id))
    assert resp.status_code == 422
    db.refresh(org)
    assert org.name == "NameGuardOrg"


def test_admin_org_patch_status_update(client, db):
    admin = _make_user(db, "pa_st@x.com", is_system_admin=True)
    org = _make_org(db, name="StatusOrg", status="pending")
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"status": "active"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_admin_org_patch_invalid_status_returns_422(client, db):
    admin = _make_user(db, "pa_inv@x.com", is_system_admin=True)
    org = _make_org(db)
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"status": "deleted"},
                        headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_org_patch_verified_update(client, db):
    admin = _make_user(db, "pa_ver@x.com", is_system_admin=True)
    org = _make_org(db, name="VerifyOrg", verified=False)
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"verified": True},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["verified"] is True
    db.refresh(org)
    assert org.verified is True


def test_admin_org_patch_categories_update(client, db):
    admin = _make_user(db, "pa_cat@x.com", is_system_admin=True)
    cat1 = _make_category(db, "OldCat")
    cat2 = _make_category(db, "NewCat")
    org = _make_org(db, name="CatOrg")
    db.add(OrganizationCategory(organization_id=org.id, category_id=cat1.id, position=0))
    db.commit()

    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"category_ids": [cat2.id]},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    cat_ids = {c["id"] for c in data["categories"]}
    assert cat_ids == {cat2.id}


def test_admin_org_patch_id_cannot_be_changed(client, db):
    admin = _make_user(db, "pa_id@x.com", is_system_admin=True)
    org = _make_org(db, name="IDGuardOrg")
    original_id = org.id
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"id": 99999, "name": "IDGuardUpdated"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["id"] == original_id


def test_admin_org_patch_response_fields(client, db):
    admin = _make_user(db, "pa_rf@x.com", is_system_admin=True)
    org = _make_org(db, name="RespFieldOrg")
    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"description": "Updated"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    assert set(resp.json().keys()) == _EXPECTED_ORG_RESPONSE_FIELDS


def test_admin_org_patch_org_users_unchanged_by_patch(client, db):
    admin = _make_user(db, "pa_usr_adm@x.com", is_system_admin=True)
    owner = _make_user(db, "pa_owner@x.com", name="Owner")
    org = _make_org(db, name="UserOrg")
    _make_org_user(db, org.id, owner.id, role="owner")

    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"name": "UserOrgRenamed"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["users"]) == 1
    assert data["users"][0]["id"] == owner.id
    assert data["users"][0]["role"] == "owner"


def test_admin_org_patch_trial_lesson_available_true_to_false(client, db):
    admin = _make_user(db, "pa_trl@x.com", is_system_admin=True)
    org = _make_org(db, name="TrialToggleOrg")
    org.trial_lesson_available = True
    org.trial_lesson_price = 99.0
    org.trial_lesson_comment = "Free first lesson"
    db.commit()

    resp = client.patch(f"/admin/organizations/{org.id}",
                        json={"trial_lesson_available": False},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["trial_lesson_available"] is False
    db.refresh(org)
    assert org.trial_lesson_available is False


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /admin/organizations/{organization_id}
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_org_delete_200_for_system_admin(client, db):
    admin = _make_user(db, "del_adm@x.com", is_system_admin=True)
    org = _make_org(db, name="DeleteMe")
    resp = client.delete(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_org_delete_403_for_normal_user(client, db):
    user = _make_user(db, "del_usr@x.com")
    org = _make_org(db, name="ForbidDel")
    resp = client.delete(f"/admin/organizations/{org.id}", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_org_delete_401_for_unauthenticated(client, db):
    org = _make_org(db, name="AnonDel")
    resp = client.delete(f"/admin/organizations/{org.id}")
    assert resp.status_code == 401


def test_admin_org_delete_404_for_missing_org(client, db):
    admin = _make_user(db, "del_404@x.com", is_system_admin=True)
    resp = client.delete("/admin/organizations/999999", headers=_auth(admin.id))
    assert resp.status_code == 404


def test_admin_org_delete_removes_org(client, db):
    admin = _make_user(db, "del_gone@x.com", is_system_admin=True)
    org = _make_org(db, name="GoneOrg")
    org_id = org.id
    resp = client.delete(f"/admin/organizations/{org_id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert db.query(Organization).filter(Organization.id == org_id).first() is None


def test_admin_org_delete_response_message(client, db):
    admin = _make_user(db, "del_msg@x.com", is_system_admin=True)
    org = _make_org(db, name="MsgOrg")
    resp = client.delete(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert "message" in resp.json()


def test_admin_org_delete_user_accounts_not_deleted(client, db):
    """Deleting an org must never delete the User accounts of its members."""
    admin = _make_user(db, "del_uadm@x.com", is_system_admin=True)
    member = _make_user(db, "del_member@x.com", name="MemberUser")
    org = _make_org(db, name="MemberOrg")
    _make_org_user(db, org.id, member.id, role="owner")

    resp = client.delete(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200

    still_exists = db.query(User).filter(User.id == member.id).first()
    assert still_exists is not None
    assert still_exists.email == "del_member@x.com"


def test_admin_org_delete_without_membership_succeeds(client, db):
    """System admin does not need to be an org member to delete."""
    admin = _make_user(db, "del_nonmem@x.com", is_system_admin=True)
    org = _make_org(db, name="NoMemberOrg")
    # admin is NOT an OrganizationUser of org
    resp = client.delete(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert db.query(Organization).filter(Organization.id == org.id).first() is None


def test_admin_org_delete_with_events_succeeds_and_org_is_gone(client, db):
    """Delete succeeds even with events; org row is gone.
    Events cascade-delete in PostgreSQL at the DB level; in SQLite tests
    they survive since FK constraints are not enforced by default.
    """
    admin = _make_user(db, "del_evadm@x.com", is_system_admin=True)
    org = _make_org(db, name="EventOrg")
    _make_event(db, org.id, title="SomeEvent")

    resp = client.delete(f"/admin/organizations/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert db.query(Organization).filter(Organization.id == org.id).first() is None
