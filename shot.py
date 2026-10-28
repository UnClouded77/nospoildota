from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/usr/bin/google-chrome")
    for name,url,vp in [("home","index.html",(1280,900)),("tournament","t/pari-universe.html",(1280,900)),("home-mobile","index.html",(390,844)),("team","team/team-spirit.html",(1280,900)),("tournaments","tournaments.html",(390,844))]:
        pg=b.new_page(viewport={"width":vp[0],"height":vp[1]});pg.goto("http://localhost:8765/"+url);pg.screenshot(path=f"screens/{name}.png",full_page=False)
    for name,url,vp,ff in [("followed","index.html",(1280,900),"0"),("followed-mobile","index.html",(390,844),"1"),("followed-team","team/team-spirit.html",(390,844),"0"),("followed-teams-index","teams.html",(1280,900),"0")]:
        pg=b.new_page(viewport={"width":vp[0],"height":vp[1]})
        pg.add_init_script(f"localStorage.setItem('nsd-follow',JSON.stringify(['spirit','liquid']));localStorage.setItem('nsd-ffirst','{ff}');localStorage.setItem('nsd-tier','all')")
        pg.goto("http://localhost:8765/"+url);pg.screenshot(path=f"screens/{name}.png",full_page=False)
    pg=b.new_page(viewport={"width":390,"height":844});pg.add_init_script("localStorage.setItem('nsd-follow',JSON.stringify(['spirit']));localStorage.setItem('nsd-mine','1')")
    pg.goto("http://localhost:8765/index.html");pg.screenshot(path="screens/my-teams-mobile.png")
    b.close()
