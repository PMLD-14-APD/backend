"""
Isi data master awal (aman dijalankan berulang, tidak bikin duplikat).
    python seed_master_data.py

PENTING: label_key harus sama persis dengan nama kelas yang dikeluarkan model AI.
Sesuaikan dengan AI Ops sebelum dipakai betulan.
"""

from app.core.database import SessionLocal
from app.models import user, activity_log, environment, ai_model, video_source, analysis  # noqa: F401
from app.models.ai_model import ApdClass, EnvironmentApdClass
from app.models.environment import Environment

ENVIRONMENT = {"name": "Konstruksi", "description": "Area proyek konstruksi"}

# (name, label_key, description, wajib?)
APD_CLASSES = [
    ("Helm", "helmet", "Helm keselamatan", True),
    ("Rompi", "vest", "Rompi keselamatan", True),
]


def main():
    db = SessionLocal()
    try:
        env = db.query(Environment).filter(Environment.name == ENVIRONMENT["name"]).first()
        if env is None:
            env = Environment(**ENVIRONMENT)
            db.add(env)
            db.flush()
            print(f"+ environment '{env.name}'")

        for name, label_key, description, mandatory in APD_CLASSES:
            apd = db.query(ApdClass).filter(ApdClass.label_key == label_key).first()
            if apd is None:
                apd = ApdClass(name=name, label_key=label_key, description=description)
                db.add(apd)
                db.flush()
                print(f"+ apd class '{label_key}'")

            link = (
                db.query(EnvironmentApdClass)
                .filter(
                    EnvironmentApdClass.environment_id == env.id,
                    EnvironmentApdClass.apd_class_id == apd.id,
                )
                .first()
            )
            if link is None:
                db.add(EnvironmentApdClass(environment_id=env.id, apd_class_id=apd.id, is_mandatory=mandatory))
                print(f"+ relasi {env.name} -> {label_key}")

        db.commit()
        print("Seed selesai.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
