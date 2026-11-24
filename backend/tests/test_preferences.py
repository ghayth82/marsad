"""مظهر الواجهة لكل مستخدم (ملاحظة غيث 15)."""


def test_appearance_saved_validated_and_defaulted(admin):
    c = admin
    p = c.get("/api/me").json()["preferences"]
    assert p["appearance"] == {"font": "noto", "leading": "comfy", "read_scale": 1.0, "read_width": "medium",
                               "accent": "teal", "contrast": False, "density": "comfortable"}
    r = c.patch("/api/me/preferences", json={"theme": "dark", "appearance": {"font": "naskh", "accent": "blue", "read_scale": 1.5}})
    assert r.status_code == 200, r.text
    p = c.get("/api/me").json()["preferences"]
    assert p["theme"] == "dark" and p["appearance"]["font"] == "naskh" and p["appearance"]["density"] == "comfortable"
    # لون غير مفحوص أو حجم خارج الحدود يُرفض
    assert c.patch("/api/me/preferences", json={"appearance": {"accent": "red"}}).status_code == 422
    assert c.patch("/api/me/preferences", json={"appearance": {"read_scale": 5}}).status_code == 422
