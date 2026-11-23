"""الحالة 40: مستخدمان يعدّلان الادّعاء نفسه — يرى كل منهما الآخر، ولا يضيع أي تعديل."""

from tests.conftest import invite_user


def test_case40_two_users_same_claim(admin, make_client):
    from marsad.api import presence

    presence.reset()
    ed, _ = invite_user(admin, make_client, "ed@example.com", ["editor"])
    cid = admin.post("/api/claims", json={"text": "ادّعاء يعمل عليه اثنان"}).json()["id"]
    # الحضور: كل منهما يرى الآخر، ومن يكتب يظهر «يكتب»
    assert admin.post("/api/presence", json={"path": f"/claims/{cid}"}).json()["others"] == []
    seen = ed.post("/api/presence", json={"path": f"/claims/{cid}", "editing": True}).json()["others"]
    assert [o["name"] for o in seen] == ["غيث"]
    seen = admin.post("/api/presence", json={"path": f"/claims/{cid}"}).json()["others"]
    assert seen[0]["name"] == "ed" and seen[0]["editing"] is True
    assert admin.post("/api/presence", json={"path": "/admin"}).status_code == 422
    # حقلان مختلفان في الوقت نفسه: يُحفظ الاثنان
    assert admin.put(f"/api/claims/{cid}", json={"speaker": "وزير المالية", "base": {"speaker": ""}}).status_code == 200
    assert ed.put(f"/api/claims/{cid}", json={"tags": ["اقتصاد"], "base": {"tags": []}}).status_code == 200
    c = admin.get(f"/api/claims/{cid}").json()
    assert c["speaker"] == "وزير المالية" and c["tags"] == ["اقتصاد"]
    # الحقل نفسه: الثاني يُرفض بالقيمة الحالية بدل أن يمحو تعديل الأول
    assert admin.put(f"/api/claims/{cid}", json={"text": "صياغة غيث", "base": {"text": "ادّعاء يعمل عليه اثنان"}}).status_code == 200
    r = ed.put(f"/api/claims/{cid}", json={"text": "صياغة المحرّر", "base": {"text": "ادّعاء يعمل عليه اثنان"}})
    assert r.status_code == 409 and r.json()["current"]["text"] == "صياغة غيث"
    assert admin.get(f"/api/claims/{cid}").json()["text"] == "صياغة غيث"
    # الأدلة تُضاف ولا تُستبدل: إضافتان متزامنتان تبقيان
    admin.post(f"/api/claims/{cid}/evidence", json={"kind": "link", "title": "دليل غيث", "url": "https://a.example"})
    ed.post(f"/api/claims/{cid}/evidence", json={"kind": "link", "title": "دليل المحرّر", "url": "https://b.example"})
    assert {e["title"] for e in admin.get(f"/api/claims/{cid}").json()["evidence"]} == {"دليل غيث", "دليل المحرّر"}
