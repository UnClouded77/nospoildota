from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/usr/bin/google-chrome")
    for name,url,vp in [("home","index.html",(1280,900)),("tournament","t/pari-universe.html",(1280,900)),("home-mobile","index.html",(390,844))]:
        pg=b.new_page(viewport={"width":vp[0],"height":vp[1]});pg.goto("http://localhost:8765/"+url);pg.screenshot(path=f"screens/{name}.png",full_page=False)
    b.close()
