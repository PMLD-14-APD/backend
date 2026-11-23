from app.services.inference.compliance import KURANG, LENGKAP, TIDAK, evaluate
from app.services.inference.detector import (
    Detection,
    compute_crop_rect,
    filter_person_detections,
    select_final_ppe,
)
from app.services.inference.tracker import IouTracker

REQ = ["helmet", "vest"]
PERSON = (100, 100, 200, 300)


def D(label, box, conf=0.9):
    return Detection(label, conf, box)


def test_lengkap():
    dets = [D("person", PERSON), D("helmet", (120, 100, 180, 140)), D("vest", (110, 150, 190, 230))]
    (p,) = evaluate(dets, REQ, "person")
    assert p.status == LENGKAP and p.missing == []


def test_kurang_lengkap():
    (p,) = evaluate([D("person", PERSON), D("helmet", (120, 100, 180, 140))], REQ, "person")
    assert p.status == KURANG and p.missing == ["vest"]


def test_tidak_digunakan():
    (p,) = evaluate([D("person", PERSON)], REQ, "person")
    assert p.status == TIDAK and p.missing == REQ


def test_apd_di_luar_box_orang_diabaikan():
    (p,) = evaluate([D("person", PERSON), D("helmet", (400, 400, 450, 450))], REQ, "person")
    assert p.status == TIDAK


def test_apd_diberikan_ke_orang_terkecil_yang_memuatnya():
    besar, kecil = (0, 0, 400, 400), (100, 100, 200, 300)
    r_besar, r_kecil = evaluate([D("person", besar), D("person", kecil), D("helmet", (120, 100, 180, 140))],
                                REQ, "person")
    assert "helmet" in r_kecil.present and "helmet" not in r_besar.present


def test_tanpa_orang_tidak_ada_hasil():
    assert evaluate([D("helmet", (1, 1, 5, 5))], REQ, "person") == []


def test_tracker_id_stabil_dan_orang_baru_dapat_id_baru():
    t = IouTracker()
    assert t.update([(100, 100, 200, 300)], 1) == [1]
    assert t.update([(105, 100, 205, 300)], 2) == [1]                      # bergeser sedikit = orang sama
    assert t.update([(105, 100, 205, 300), (400, 100, 500, 300)], 3) == [1, 2]


def test_tracker_membuang_track_lama():
    t = IouTracker(max_age=2)
    t.update([(0, 0, 10, 10)], 1)
    t.update([], 10)
    assert t.tracks == {}


def test_filter_person_membuang_orang_kecil_dan_conf_rendah():
    raw = [
        D("person", (100, 100, 300, 600), conf=0.90),
        D("person", (10, 10, 40, 80), conf=0.80),
        D("person", (200, 100, 400, 600), conf=0.35),
    ]
    kept = filter_person_detections(raw, frame_height=1000, person_label="Person", min_conf=0.50, min_height_ratio=0.15)
    assert len(kept) == 1
    assert kept[0].label == "Person" and kept[0].conf == 0.90


def test_compute_crop_rect_dijepit_ke_batas_frame():
    assert compute_crop_rect((10, 20, 110, 220), frame_w=500, frame_h=500, padding=0.2) == (0, 0, 130, 260)


def test_select_final_ppe_buang_duplikat_bersarang_dan_konflik():
    confs = {"Hardhat": 0.15, "Safety Vest": 0.15, "NO-Hardhat": 0.10, "NO-Safety Vest": 0.20}
    dets = [
        D("Safety Vest", (0, 0, 100, 100), conf=0.35),
        D("NO-Safety Vest", (2, 2, 98, 98), conf=0.35),
        D("Safety Vest", (10, 10, 50, 90), conf=0.31),
        D("Hardhat", (200, 10, 250, 60), conf=0.17),
        D("NO-Hardhat", (300, 10, 350, 60), conf=0.65),
        D("Hardhat", (295, 5, 355, 65), conf=0.20),
    ]
    out = select_final_ppe(dets, confs, default_conf=0.25)
    labels = sorted(d.label for d in out)
    assert labels == ["Hardhat", "NO-Hardhat", "Safety Vest"], out
    assert next(d.conf for d in out if d.label == "Hardhat") == 0.17
    assert next(d.conf for d in out if d.label == "Safety Vest") == 0.35