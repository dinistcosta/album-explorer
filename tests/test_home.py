def test_home_portuguese(client):
    r = client.get("/pt/")
    assert r.status_code == 200
    assert "Pesquisa uma banda ou um álbum" in r.content.decode()


def test_home_english(client):
    r = client.get("/en/")
    assert "Search for a band or an album" in r.content.decode()


def test_root_redirects_by_accept_language(client):
    r = client.get("/", HTTP_ACCEPT_LANGUAGE="en-GB,en;q=0.9")
    assert r.status_code == 302 and r.url.startswith("/en/")
