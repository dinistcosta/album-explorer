def test_home_portuguese(client, db):
    r = client.get("/pt/")
    assert r.status_code == 200
    assert "Pesquisa uma banda ou um álbum" in r.content.decode()


def test_home_english(client, db):
    r = client.get("/en/")
    assert "Search for a band or an album" in r.content.decode()


def test_root_redirects_by_accept_language(client):
    r = client.get("/", HTTP_ACCEPT_LANGUAGE="en-GB,en;q=0.9")
    assert r.status_code == 302 and r.url.startswith("/en/")


def test_home_links_genre_rooms(client, genre_factory):
    genre_factory(name="shoegaze", featured=True)
    genre_factory(name="polka")
    html = client.get("/pt/").content.decode()
    assert 'href="/pt/genre/shoegaze/"' in html
    assert "/genre/polka/" not in html
