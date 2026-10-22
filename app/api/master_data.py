import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.activity_log import log_activity
from app.models.ai_model import AIModel, ApdClass, EnvironmentApdClass
from app.models.environment import Environment, Location
from app.models.user import User
from app.schemas.master import (
    AIModelAdminOut,
    AIModelCreate,
    AIModelOut,
    AIModelUpdate,
    ApdClassCreate,
    ApdClassOut,
    ApdClassUpdate,
    EnvironmentApdOut,
    EnvironmentApdSet,
    EnvironmentCreate,
    EnvironmentOut,
    EnvironmentUpdate,
    LocationCreate,
    LocationOut,
    LocationUpdate,
)

locations_router = APIRouter(prefix="/locations", tags=["Locations"])
environments_router = APIRouter(prefix="/environments", tags=["Environments"])
apd_classes_router = APIRouter(prefix="/apd-classes", tags=["APD Classes"])
ai_models_router = APIRouter(prefix="/ai-models", tags=["AI Models"])


# ======================================================================
# Helper
# ======================================================================
def _get_or_404(db: Session, model, obj_id: uuid.UUID, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{label} tidak ditemukan")
    return obj


def _apply_update(obj, data: dict, nullable: frozenset = frozenset()) -> None:
    for key, value in data.items():
        if value is None and key not in nullable:
            raise HTTPException(status_code=422, detail=f"Field '{key}' tidak boleh null")
        setattr(obj, key, value)


def _save(db: Session, admin: User, action: str, target_type: str, obj, detail: str,
          conflict_msg: str, target_id: Optional[uuid.UUID] = None):
    """Simpan obj + catat activity log dalam satu transaksi."""
    try:
        db.flush()
        log_activity(db, admin.id, action, target_type, target_id or obj.id, detail)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=conflict_msg)
    db.refresh(obj)
    return obj


def _remove(db: Session, admin: User, action: str, target_type: str, obj, detail: str,
            conflict_msg: str) -> dict:
    obj_id = obj.id
    try:
        db.delete(obj)
        db.flush()
        log_activity(db, admin.id, action, target_type, obj_id, detail)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=conflict_msg)
    return {"message": "Berhasil dihapus"}


# ======================================================================
# Locations
# ======================================================================
@locations_router.get("/", response_model=list[LocationOut])
def list_locations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Location).order_by(Location.name).all()


@locations_router.get("/{location_id}", response_model=LocationOut)
def get_location(location_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return _get_or_404(db, Location, location_id, "Lokasi")


@locations_router.post("/", response_model=LocationOut, status_code=201)
def create_location(payload: LocationCreate, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    obj = Location(**payload.model_dump())
    db.add(obj)
    return _save(db, admin, "location.create", "location", obj, obj.name, "Nama lokasi sudah dipakai")


@locations_router.patch("/{location_id}", response_model=LocationOut)
def update_location(location_id: uuid.UUID, payload: LocationUpdate, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    obj = _get_or_404(db, Location, location_id, "Lokasi")
    _apply_update(obj, payload.model_dump(exclude_unset=True), nullable=frozenset({"address"}))
    return _save(db, admin, "location.update", "location", obj, obj.name, "Nama lokasi sudah dipakai")


@locations_router.delete("/{location_id}")
def delete_location(location_id: uuid.UUID, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    # kamera yang memakai lokasi ini tidak ikut terhapus, location_id-nya jadi NULL (sesuai ERD: nullable)
    obj = _get_or_404(db, Location, location_id, "Lokasi")
    return _remove(db, admin, "location.delete", "location", obj, obj.name,
                   "Lokasi masih dipakai data lain, tidak bisa dihapus")


# ======================================================================
# Environments
# ======================================================================
@environments_router.get("/", response_model=list[EnvironmentOut])
def list_environments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Environment).order_by(Environment.name).all()


@environments_router.get("/{environment_id}", response_model=EnvironmentOut)
def get_environment(environment_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return _get_or_404(db, Environment, environment_id, "Environment")


@environments_router.post("/", response_model=EnvironmentOut, status_code=201)
def create_environment(payload: EnvironmentCreate, db: Session = Depends(get_db),
                       admin: User = Depends(require_admin)):
    obj = Environment(**payload.model_dump())
    db.add(obj)
    return _save(db, admin, "environment.create", "environment", obj, obj.name,
                 "Nama environment sudah dipakai")


@environments_router.patch("/{environment_id}", response_model=EnvironmentOut)
def update_environment(environment_id: uuid.UUID, payload: EnvironmentUpdate,
                       db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    obj = _get_or_404(db, Environment, environment_id, "Environment")
    _apply_update(obj, payload.model_dump(exclude_unset=True), nullable=frozenset({"description"}))
    return _save(db, admin, "environment.update", "environment", obj, obj.name,
                 "Nama environment sudah dipakai")


@environments_router.delete("/{environment_id}")
def delete_environment(environment_id: uuid.UUID, db: Session = Depends(get_db),
                       admin: User = Depends(require_admin)):
    obj = _get_or_404(db, Environment, environment_id, "Environment")
    return _remove(db, admin, "environment.delete", "environment", obj, obj.name,
                   "Environment masih dipakai kamera atau model AI, tidak bisa dihapus")


# ---------- APD wajib per environment ----------
@environments_router.get("/{environment_id}/apd-classes", response_model=list[EnvironmentApdOut])
def list_environment_apd(environment_id: uuid.UUID, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    _get_or_404(db, Environment, environment_id, "Environment")
    rows = (
        db.query(EnvironmentApdClass)
        .options(joinedload(EnvironmentApdClass.apd_class))
        .filter(EnvironmentApdClass.environment_id == environment_id)
        .all()
    )
    return sorted(rows, key=lambda r: r.apd_class.name)


@environments_router.put(
    "/{environment_id}/apd-classes/{apd_class_id}", response_model=EnvironmentApdOut
)
def set_environment_apd(
    environment_id: uuid.UUID,
    apd_class_id: uuid.UUID,
    payload: EnvironmentApdSet = EnvironmentApdSet(),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Tambahkan APD ke environment, atau ubah is_mandatory kalau sudah ada (idempotent)."""
    env = _get_or_404(db, Environment, environment_id, "Environment")
    apd = _get_or_404(db, ApdClass, apd_class_id, "APD class")

    row = (
        db.query(EnvironmentApdClass)
        .filter(
            EnvironmentApdClass.environment_id == environment_id,
            EnvironmentApdClass.apd_class_id == apd_class_id,
        )
        .first()
    )
    if row is None:
        row = EnvironmentApdClass(
            environment_id=environment_id,
            apd_class_id=apd_class_id,
            is_mandatory=payload.is_mandatory,
        )
        db.add(row)
    else:
        row.is_mandatory = payload.is_mandatory

    detail = f"{env.name} | {apd.label_key} | wajib={payload.is_mandatory}"
    return _save(db, admin, "environment_apd.set", "environment", row, detail,
                 "Relasi environment dan APD sudah ada", target_id=env.id)


@environments_router.delete("/{environment_id}/apd-classes/{apd_class_id}")
def remove_environment_apd(environment_id: uuid.UUID, apd_class_id: uuid.UUID,
                           db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    row = (
        db.query(EnvironmentApdClass)
        .filter(
            EnvironmentApdClass.environment_id == environment_id,
            EnvironmentApdClass.apd_class_id == apd_class_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Relasi environment dan APD tidak ditemukan")

    env = db.get(Environment, environment_id)
    apd = db.get(ApdClass, apd_class_id)
    detail = f"{env.name} | {apd.label_key}"
    row_env_id = env.id
    try:
        db.delete(row)
        db.flush()
        log_activity(db, admin.id, "environment_apd.remove", "environment", row_env_id, detail)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Relasi tidak bisa dihapus")
    return {"message": "Berhasil dihapus"}


# ======================================================================
# APD classes
# ======================================================================
@apd_classes_router.get("/", response_model=list[ApdClassOut])
def list_apd_classes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ApdClass).order_by(ApdClass.name).all()


@apd_classes_router.get("/{apd_class_id}", response_model=ApdClassOut)
def get_apd_class(apd_class_id: uuid.UUID, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return _get_or_404(db, ApdClass, apd_class_id, "APD class")


@apd_classes_router.post("/", response_model=ApdClassOut, status_code=201)
def create_apd_class(payload: ApdClassCreate, db: Session = Depends(get_db),
                     admin: User = Depends(require_admin)):
    obj = ApdClass(**payload.model_dump())
    db.add(obj)
    return _save(db, admin, "apd_class.create", "apd_class", obj, obj.label_key,
                 "label_key sudah dipakai")


@apd_classes_router.patch("/{apd_class_id}", response_model=ApdClassOut)
def update_apd_class(apd_class_id: uuid.UUID, payload: ApdClassUpdate,
                     db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    obj = _get_or_404(db, ApdClass, apd_class_id, "APD class")
    _apply_update(obj, payload.model_dump(exclude_unset=True), nullable=frozenset({"description"}))
    return _save(db, admin, "apd_class.update", "apd_class", obj, obj.label_key,
                 "label_key sudah dipakai")


@apd_classes_router.delete("/{apd_class_id}")
def delete_apd_class(apd_class_id: uuid.UUID, db: Session = Depends(get_db),
                     admin: User = Depends(require_admin)):
    obj = _get_or_404(db, ApdClass, apd_class_id, "APD class")
    return _remove(db, admin, "apd_class.delete", "apd_class", obj, obj.label_key,
                   "APD class masih dipakai environment atau data deteksi, tidak bisa dihapus")


# ======================================================================
# AI models
# ======================================================================
@ai_models_router.get("/", response_model=list[AIModelOut])
def list_ai_models(
    environment_id: Optional[uuid.UUID] = None,
    is_active: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(AIModel)
    if environment_id:
        q = q.filter(AIModel.environment_id == environment_id)
    if is_active is not None:
        q = q.filter(AIModel.is_active == is_active)
    return q.order_by(AIModel.name, AIModel.version).all()


@ai_models_router.get("/{model_id}", response_model=AIModelOut)
def get_ai_model(model_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return _get_or_404(db, AIModel, model_id, "Model AI")


@ai_models_router.post("/", response_model=AIModelAdminOut, status_code=201)
def create_ai_model(payload: AIModelCreate, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    _get_or_404(db, Environment, payload.environment_id, "Environment")
    obj = AIModel(**payload.model_dump())
    db.add(obj)
    return _save(db, admin, "ai_model.create", "ai_model", obj, f"{obj.name} {obj.version}",
                 "Data model AI tidak valid")


@ai_models_router.patch("/{model_id}", response_model=AIModelAdminOut)
def update_ai_model(model_id: uuid.UUID, payload: AIModelUpdate, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    obj = _get_or_404(db, AIModel, model_id, "Model AI")
    data = payload.model_dump(exclude_unset=True)
    if data.get("environment_id") is not None:
        _get_or_404(db, Environment, data["environment_id"], "Environment")
    _apply_update(obj, data)
    return _save(db, admin, "ai_model.update", "ai_model", obj, f"{obj.name} {obj.version}",
                 "Data model AI tidak valid")


@ai_models_router.delete("/{model_id}")
def delete_ai_model(model_id: uuid.UUID, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    obj = _get_or_404(db, AIModel, model_id, "Model AI")
    return _remove(db, admin, "ai_model.delete", "ai_model", obj, f"{obj.name} {obj.version}",
                   "Model AI masih dipakai data deteksi, tidak bisa dihapus (nonaktifkan saja lewat is_active)")
