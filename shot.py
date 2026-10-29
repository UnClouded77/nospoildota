from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/usr/bin/google-chrome")
    for name,url,vp in [("home","index.html",(1280,900)),("home-mobile","index.html",(390,844)),("tournament","t/pari-universe.html",(1280,900)),("tournament-mobile","t/pari-universe.html",(390,844))]:
        pg=b.new_page(viewport={"width":vp[0],"height":vp[1]});pg.on("pageerror",lambda x:errs.append(str(x)))
        pg.goto("http://localhost:8765/"+url);pg.screenshot(path=f"screens/{name}.png",full_page=False)
        print(name, pg.evaluate("[document.querySelectorAll('#ls-list .m').length,document.querySelectorAll('.badge').length,document.querySelectorAll('h3.day').length]"))
    b.close()
print("JS errors:",errs)
