from app.services.inference.compliance import KURANG, LENGKAP, TIDAK, evaluate
from app.services.inference.detector import Detection
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