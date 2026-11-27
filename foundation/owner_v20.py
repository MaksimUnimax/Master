"""Preserve the existing multi-workshop implementation behind a default-off flag."""
def apply(root):
    f=root/"platform_core/chat_worker.py";s=f.read_text()
    a='            "PATH": os.environ["PATH"],'
    assert s.count(a)==1
    s=s.replace(a,a+'\n            "PODMASTERYE_MULTI_WORKSHOP": "1" if os.getenv("PODMASTERYE_MULTI_WORKSHOP")=="1" else "0",')
    f.write_text(s)
