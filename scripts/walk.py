#!/usr/bin/env python3
"""walk.py: a text-mode browser for one walker, backed by the headless Chrome on :9222.

Each invocation opens its own isolated browser context (so six walkers never share a
tab), restores this shape's cookies from a state file, does one thing, prints a page
report, and saves the cookies back. Nothing here bypasses the product: every action is
a real page load, click or form submit through the same HTML a person would use.

This is a host-side developer tool, not a product dependency: it needs `playwright`
installed in the HOST Python, so do NOT add it to `pyproject.toml` or
`requirements.lock`. It talks to the headless Chrome already running on :9222 and
falls back to a private headless chromium when that port is unreachable. It never
proposes un-headlessing the :9222 Chrome.

Usage (always pass --shape N first):
  walk.py --shape 1 login
  walk.py --shape 1 get /surface/rights/            [--full] [--raw]
  walk.py --shape 1 click /path "Link or button text"   (or "css=.selector")
  walk.py --shape 1 fill /path --set name=value --set file_field=@/abs/path.csv [--submit "Button text"] [--form 0]
  walk.py --shape 1 shot /path /abs/out.png         [--full]
  walk.py --shape 1 js /path "document.title"
"""
import argparse, json, os, sys, time
from playwright.sync_api import sync_playwright

STATE_DIR = os.environ.get("OPENH2O_WALK_STATE", "/tmp/openh2o-walk-state")
LOGIN = "shape{n}@local.test"
PASSWORD = "password123"


def base(n):
    return f"http://localhost:810{n}"


def state_path(n):
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, f"shape-{n}.json")


def open_context(pw, n):
    try:
        browser = pw.chromium.connect_over_cdp("http://localhost:9222", timeout=8000)
    except Exception as exc:  # the :9222 Chrome is down; a private headless one is equivalent
        sys.stderr.write(f"[walk] :9222 unreachable ({exc.__class__.__name__}); launching a private headless chromium\n")
        browser = pw.chromium.launch(headless=True)
    sp = state_path(n)
    kwargs = {"viewport": {"width": 1440, "height": 900}}
    if os.path.exists(sp):
        kwargs["storage_state"] = sp
    ctx = browser.new_context(**kwargs)
    ctx.set_default_timeout(20000)
    return browser, ctx


def settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass


def report(page, status, full=False, raw=False):
    out = []
    out.append(f"URL: {page.url}")
    out.append(f"STATUS: {status}")
    out.append(f"TITLE: {page.title()}")
    if raw:
        out.append("--- HTML ---")
        out.append(page.content())
        return "\n".join(out)
    data = page.evaluate(
        """() => {
      const txt = (el) => (el ? el.innerText.replace(/\\n{3,}/g, '\\n\\n').trim() : '');
      const main = document.querySelector('main') || document.body;
      const heads = [...document.querySelectorAll('h1,h2,h3')].map(h => h.tagName + ': ' + h.innerText.trim()).filter(Boolean);
      const alerts = [...document.querySelectorAll('.errorlist, .alert, [role=alert], .invalid-feedback, .messages li, .message, .form-error, .help-block.error, .text-danger, .error')]
          .map(e => e.innerText.trim()).filter(Boolean);
      const nav = [...document.querySelectorAll('nav a, aside a, .sidebar a')].map(a => a.innerText.trim() + ' -> ' + a.getAttribute('href')).filter(s => !s.startsWith(' ->'));
      const header = [...document.querySelectorAll('a[href], button, input[type=submit]')]
          .filter(e => !e.closest('main') && !e.closest('nav.sidebar-nav') && !e.closest('footer') && !e.closest('#feedback-modal, .feedback-modal, [id*=feedback]'))
          .map(e => (e.innerText || e.value || '').trim().replace(/\\s+/g, ' ') + ' -> ' + (e.getAttribute('href') || e.getAttribute('hx-get') || e.getAttribute('hx-post') || 'button'))
          .filter(s => !s.startsWith(' ->') && !/^(Skip to main content|Sign out|About|Source code|×|Bug|Idea|Question|Data looks wrong|Attach a screenshot|Send feedback)\b/.test(s) && !s.includes('@'));
      const links = [];
      const seen = new Set();
      for (const a of document.querySelectorAll('a[href]')) {
        if (a.closest('nav.sidebar-nav')) continue;
        const t = a.innerText.trim().replace(/\\s+/g, ' ');
        const h = a.getAttribute('href');
        const k = t + '|' + h;
        if (!t || seen.has(k)) continue;
        seen.add(k); links.push(t + ' -> ' + h);
      }
      const forms = [...document.querySelectorAll('form')].map((f, i) => {
        const fields = [...f.querySelectorAll('input, select, textarea')].filter(el => el.type !== 'hidden').map(el => {
          let label = '';
          if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) label = l.innerText.trim(); }
          if (!label && el.closest('label')) label = el.closest('label').innerText.trim();
          const d = {name: el.name, type: el.tagName === 'INPUT' ? el.type : el.tagName.toLowerCase(), label};
          if (el.required) d.required = true;
          if (el.tagName === 'SELECT') d.options = [...el.options].map(o => o.value + (o.textContent.trim() !== o.value ? ' (' + o.textContent.trim() + ')' : '')).slice(0, 60);
          if (el.value && el.type !== 'password' && el.type !== 'file') d.value = el.value.slice(0, 80);
          if (el.placeholder) d.placeholder = el.placeholder;
          return d;
        });
        const buttons = [...f.querySelectorAll('button, input[type=submit]')].map(b => (b.innerText || b.value || '').trim()).filter(Boolean);
        return {index: i, action: f.getAttribute('action') || '', method: (f.getAttribute('method') || 'get').toUpperCase(), enctype: f.getAttribute('enctype') || '', fields, buttons, hx: f.getAttribute('hx-post') || f.getAttribute('hx-get') || ''};
      });
      const buttons = [...main.querySelectorAll('button, [role=button]')].map(b => b.innerText.trim()).filter(Boolean);
      const hx = [...main.querySelectorAll('[hx-get],[hx-post]')].map(e => (e.innerText.trim().slice(0,40) || e.tagName) + ' => ' + (e.getAttribute('hx-get') ? 'GET ' + e.getAttribute('hx-get') : 'POST ' + e.getAttribute('hx-post')));
      return {text: txt(main), heads, alerts, nav, links, forms, buttons, hx, header};
    }"""
    )
    if data["alerts"]:
        out.append("ALERTS/ERRORS: " + " | ".join(data["alerts"]))
    out.append("HEADINGS: " + " | ".join(data["heads"]))
    out.append("SIDEBAR: " + " | ".join(dict.fromkeys(data["nav"])))
    out.append("PAGE ACTIONS (header, above the main area; a person sees these first): " + (" | ".join(dict.fromkeys(data["header"])) or "none"))
    text = data["text"]
    cap = None if full else 6000
    if cap and len(text) > cap:
        text = text[:cap] + f"\n[... {len(data['text']) - cap} more characters; re-run with --full]"
    out.append("--- MAIN TEXT ---")
    out.append(text)
    out.append("--- LINKS ---")
    out.append("\n".join(data["links"][: (None if full else 120)]))
    if data["hx"]:
        out.append("--- HTMX ACTIONS ---")
        out.append("\n".join(dict.fromkeys(data["hx"][: (None if full else 60)])))
    if data["buttons"]:
        out.append("--- BUTTONS --- " + " | ".join(dict.fromkeys(data["buttons"])))
    if data["forms"]:
        out.append("--- FORMS ---")
        out.append(json.dumps(data["forms"], indent=1))
    return "\n".join(out)


def goto(page, n, path):
    url = path if path.startswith("http") else base(n) + path
    resp = page.goto(url, wait_until="domcontentloaded")
    settle(page)
    return resp.status if resp else None


def do_login(page, n):
    goto(page, n, "/accounts/login/")
    if page.locator("input[name=login]").count() == 0:
        return "/accounts/login/" not in page.url
    page.fill("input[name=login]", LOGIN.format(n=n))
    page.fill("input[name=password]", PASSWORD)
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.click("form button[type=submit], form input[type=submit]")
    settle(page)
    ok = "/accounts/login/" not in page.url
    return ok


def set_field(page, form, name, value):
    loc = form.locator(f"[name='{name}']").first
    if loc.count() == 0:
        raise SystemExit(f"[walk] no field named {name!r} in that form")
    tag = loc.evaluate("el => el.tagName.toLowerCase()")
    typ = loc.evaluate("el => el.type || ''")
    if value.startswith("@"):
        loc.set_input_files(value[1:])
    elif tag == "select":
        try:
            loc.select_option(value=value)
        except Exception:
            loc.select_option(label=value)
    elif typ in ("checkbox", "radio"):
        if typ == "radio":
            form.locator(f"[name='{name}'][value='{value}']").check()
        elif value.lower() in ("1", "true", "on", "yes"):
            loc.check()
        else:
            loc.uncheck()
    else:
        try:
            if loc.is_visible():
                loc.fill(value)
            else:
                loc.evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }", value)
                sys.stderr.write(f"[walk] {name} is not visible (a widget hides it); value set directly\n")
        except Exception:
            loc.evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }", value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shape", type=int, required=True)
    ap.add_argument("cmd", choices=["login", "get", "click", "fill", "shot", "js"])
    ap.add_argument("path", nargs="?", default="/")
    ap.add_argument("arg", nargs="?", default=None)
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--submit", default=None)
    ap.add_argument("--then-click", default=None, help="after the submit, click this button or link on the page that came back (a preview -> commit flow)")
    ap.add_argument("--form", type=int, default=None)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()
    n = a.shape
    with sync_playwright() as pw:
        browser, ctx = open_context(pw, n)
        page = ctx.new_page()
        try:
            if a.cmd == "login":
                ok = do_login(page, n)
                print(("LOGGED IN as " if ok else "LOGIN FAILED for ") + LOGIN.format(n=n))
                print(report(page, 200 if ok else None))
            elif a.cmd == "get":
                st = goto(page, n, a.path)
                print(report(page, st, a.full, a.raw))
            elif a.cmd == "shot":
                st = goto(page, n, a.path)
                os.makedirs(os.path.dirname(a.arg), exist_ok=True)
                page.screenshot(path=a.arg, full_page=a.full)
                print(f"SHOT {a.arg} ({st}) {page.url}")
            elif a.cmd == "js":
                goto(page, n, a.path)
                print(json.dumps(page.evaluate(a.arg), indent=1, default=str))
            elif a.cmd == "click":
                goto(page, n, a.path)
                target = a.arg
                if target.startswith("css="):
                    loc = page.locator(target[4:]).first
                else:
                    loc = page.get_by_role("link", name=target, exact=True)
                    if loc.count() == 0:
                        loc = page.get_by_role("button", name=target, exact=True)
                    if loc.count() == 0:
                        loc = page.get_by_text(target, exact=False).first
                if loc.count() == 0:
                    raise SystemExit(f"[walk] nothing matching {target!r} on {page.url}")
                loc.click()
                time.sleep(0.5)
                settle(page)
                print(report(page, "after click", a.full))
            elif a.cmd == "fill":
                goto(page, n, a.path)
                forms = page.locator("form")
                if a.form is not None:
                    form = forms.nth(a.form)
                else:
                    # the first form that has every named field
                    form = None
                    for i in range(forms.count()):
                        f = forms.nth(i)
                        if all(f.locator(f"[name='{s.split('=',1)[0]}']").count() > 0 for s in a.set):
                            form = f
                            break
                    if form is None:
                        raise SystemExit("[walk] no form holds all the named fields; pass --form N (see FORMS in `get`)")
                for s in a.set:
                    name, value = s.split("=", 1)
                    set_field(page, form, name, value)
                if a.submit:
                    btn = form.get_by_role("button", name=a.submit, exact=False)
                    if btn.count() == 0:
                        btn = form.locator(f"input[type=submit][value*='{a.submit}']")
                    if btn.count() == 0:
                        btn = page.get_by_role("button", name=a.submit, exact=False)
                    btn.first.click()
                else:
                    sub = form.locator("button[type=submit], input[type=submit], button:not([type])")
                    if sub.count() > 0:
                        sub.first.click()
                    else:
                        form.evaluate("f => f.requestSubmit()")
                time.sleep(0.8)
                settle(page)
                if a.then_click:
                    nxt = page.get_by_role("button", name=a.then_click, exact=False)
                    if nxt.count() == 0:
                        nxt = page.get_by_role("link", name=a.then_click, exact=False)
                    if nxt.count() == 0:
                        print(report(page, "after submit (then-click target not found)", a.full))
                        raise SystemExit(f"[walk] nothing matching {a.then_click!r} on the page that came back")
                    nxt.first.click()
                    time.sleep(0.8)
                    settle(page)
                    print(report(page, "after submit and then-click", a.full))
                else:
                    print(report(page, "after submit", a.full))
        finally:
            ctx.storage_state(path=state_path(n))
            ctx.close()


if __name__ == "__main__":
    main()
