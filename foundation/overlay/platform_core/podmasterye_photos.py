"""Workshop-scoped image attachments. Re-encode, strip metadata, limit memory."""
import base64
import binascii
import io
import warnings
from .identity import _principal
from . import podmasterye_book as book,podmasterye_workshops as workshops

def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS pm_product_photos(
      product TEXT PRIMARY KEY REFERENCES pm_products(id) ON DELETE CASCADE,
      workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
      image BLOB NOT NULL)""")
def decode_image(encoded):
    from PIL import Image,ImageOps,UnidentifiedImageError
    if not isinstance(encoded,str) or len(encoded)>710000:raise ValueError("Фото до 512 КБ.")
    try:raw=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):raise ValueError("Некорректный файл.") from None
    if not 0<len(raw)<=512*1024:raise ValueError("Фото до 512 КБ.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error",Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw),formats=["JPEG","PNG","WEBP"]) as im:
                if im.width*im.height>12_000_000:raise ValueError("Фото до 12 мегапикселей.")
                im=ImageOps.exif_transpose(im).convert("RGB");im.thumbnail((960,960))
                out=io.BytesIO();im.save(out,"JPEG",quality=82,optimize=True)
                return out.getvalue()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as e:
        raise ValueError("Поддерживаются JPEG, PNG и WebP.") from None
def get(store,token,workshop,product):
    with store._lock:
        _,a=_principal(store._db,token);w=workshops.resolve(store._db,a,workshop)
        row=store._db.execute("SELECT image FROM pm_product_photos WHERE workspace=? AND product=?",(w,product)).fetchone()
        if not row:raise ValueError("Фото не найдено.")
        return row[0]
def set_photo(store,token,workshop,product,content):
    raw=None if content is None else decode_image(content)
    with store._write() as db:
        _,a=_principal(db,token);w=workshops.resolve(db,a,workshop)
        pid,_=book.entity(db,w,"product",product)
        if raw is None:db.execute("DELETE FROM pm_product_photos WHERE workspace=? AND product=?",(w,pid))
        else:db.execute("INSERT INTO pm_product_photos VALUES(?,?,?) ON CONFLICT(product) DO UPDATE SET image=excluded.image",(pid,w,raw))
        return {"product":pid,"has_photo":raw is not None}
