"""Upstream-specific changes for Podmasterye v19."""
def apply(root):
    f=root/"platform_core/admin_statistics.py";s=f.read_text()
    a="    from .podmasterye_admin_web import nav"
    assert s.count(a)==1
    s=s.replace(a,"    from .podmasterye_admin_web import nav as admin_sidebar\n    from .web_ui import version_asset_urls")
    s=s.replace('admin_nav=nav("statistics")','admin_nav=admin_sidebar("statistics")')
    a="    return HTMLResponse(template.substitute(\n        admin_nav=admin_sidebar("
    assert s.count(a)==1
    s=s.replace(a,"    return HTMLResponse(version_asset_urls(template.substitute(\n        admin_nav=admin_sidebar(")
    a='message=escape(message), message_role="alert" if status >= 400 else "status"),'
    assert s.count(a)==1
    s=s.replace(a,a[:-2]+")),")
    f.write_text(s)
