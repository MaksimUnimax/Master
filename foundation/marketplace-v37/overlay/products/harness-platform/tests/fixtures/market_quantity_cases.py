"""Synthetic values in documented or observed structural shapes; not live evidence.

``response_for(template_id, request, context)`` is stateless: retrying a request
returns exactly the same response. The queue tests can inject faults before it
and advance their virtual clock without changing any adapter or its policy.
Report/task IDs and object URLs below are deliberately fake test artifacts.
"""
from copy import deepcopy
import csv
from datetime import datetime, timezone
import io
import zipfile

TEMPLATES = tuple([f"OZ-{i:02d}" for i in range(1, 8)] +
                  [f"WB-{i:02d}" for i in range(1, 6)] +
                  [f"YM-{i:02d}" for i in range(1, 7)])
NOW = int(datetime(2026, 11, 28, 10, tzinfo=timezone.utc).timestamp())


def context_for(template_id, **changes):
    provider = "ozon" if template_id.startswith("OZ") else "wb" if template_id.startswith("WB") else "yandex_market"
    result = {"provider": provider, "store": "test-store", "cid": "test-connection", "version": 7,
              "seller": "1001" if provider == "ozon" else "test-seller-uuid" if provider == "wb" else "12",
              "client_id": "1001", "businessId": 12, "campaignId": 123, "placementType": "FBS",
              "from": "2026-10-01", "to": "2026-10-30", "month": "2026-10", "now": NOW,
              "posting_number": "111111-0001-1", "scheme": "FBO", "token_class": "personal"}
    result.update(changes)
    return result


def csv_bytes(fields, rows):
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(fields)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def zip_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return stream.getvalue()


def ozon_csv(scheme="FBO", day="2026-10-01"):
    posting = "111111-0001-1" if scheme == "FBO" else "222222-0002-1"
    return csv_bytes(["Номер отправления", "Номер заказа", "SKU", "Принят в обработку", "Количество", "Статус",
                      "Артикул", "Название товара", "Цена", "Получатель"],
                     [[posting, posting.rsplit("-", 1)[0], "101", day+" 10:00:00", "3", "Доставлен",
                       "item-a", "Изделие A", "999999", "buyer-data-must-not-survive"]])


def yandex_realization_zip(day="2026-10-01"):
    return zip_bytes({
        name+".csv": csv_bytes(["ORDER_ID", "YOUR_SKU", "OFFER_NAME", quantity, event_date, "ORGANIZATION", "PRICE"],
                               [["9001", "item-a", "Изделие A", str(n), day, "buyer-data-must-not-survive", "999999"]])
        for name, quantity, event_date, n in [
            ("delivered", "DELIVERED_COUNT", "DELIVERY_DATE", 5),
            ("returned", "RETURNED_COUNT", "RETURN_WAREHOUSE_OR_SC_ACCEPT_DATE", 1),
            ("unredeemed", "UNREDEEMED_COUNT", "UNREDEEMED_WAREHOUSE_OR_SC_ACCEPT_DATE", 2)]})


def yandex_stocks_zip(fby=False, current=False, placement="FBS"):
    if fby:
        return zip_bytes({"stocks_on_warehouses.csv": csv_bytes(
            ["SHOP_SKU", "PRODUCT_NAME", "VALID", "RESERVED", "AVAILABLE_FOR_ORDER", "WAREHOUSE"],
            [["item-a", "Изделие A", "10", "2", "8", "Склад Маркета"]])})
    if current:
        # The live v3 report's quantity header differs from its reference page.
        # The fixture filename is synthetic; the single sheet is identified by
        # its exact quantity columns and the verified warehouse/campaign scope.
        return zip_bytes({"current_stocks.csv": csv_bytes(
            ["ERRORS", "SHOP_SKU", "PRODUCT_NAME", "WAREHOUSE", "COUNT", "RESERVE", "PRICE", "STATUS", "COMMENT"],
            [["", "item-a", "Изделие A", "Склад магазина", "8", "2", "999999", "ACTIVE", ""]])})
    return zip_bytes({"stocks_business.csv": csv_bytes(
        ["SHOP_SKU", "PRODUCT_NAME", "COUNT", "RESERVE", "WAREHOUSE_AND_SHOP", "PLACEMENT_TYPE", "ERRORS", "PRICE"],
        [["item-a", "Изделие A", "8", "2", "Склад магазина", placement, "", "999999"]])})


def posting(scheme="FBO", day="2026-10-01", **changes):
    result = {"posting_number": "111111-0001-1" if scheme == "FBO" else "222222-0002-1",
              "order_id": 9001 if scheme == "FBO" else 9002, "status": "delivered", "in_process_at": day+"T10:00:00Z",
              "products": [{"sku": 101, "offer_id": "item-a", "name": "Изделие A", "quantity": 3, "price": "999999"}],
              "customer": {"name": "buyer-data-must-not-survive"}}
    result.update(changes)
    return result


def ozon_return(**changes):
    result = {"id": 8001, "posting_number": "111111-0001-1", "schema": "Fbo", "type": "ClientReturn",
              "product": {"sku": 101, "quantity": 1, "price": {"price": "999999", "currency_code": "RUB"}},
              "exemplars": [{"id": 7001, "exemplar_id": 6001}],
              "visual": {"status": {"sys_name": "ArrivedAtReturnPlace"}, "change_moment": "2026-10-04T10:00:00Z"}}
    result.update(changes)
    return result


def wb_card(n=101):
    return {"nmID": n, "vendorCode": "item-"+str(n), "title": "Изделие "+str(n), "subjectID": 4,
            "photos": [{"big": "https://example.invalid/photo.jpg"}]}


def wb_funnel(context, n=101, ordered=12, lost=3, buyout=9):
    return {"product": {"nmId": n, "vendorCode": "item-"+str(n), "title": "Изделие "+str(n), "subjectId": 4},
            "statistic": {"selected": {"period": {"start": context["from"], "end": context["to"]},
                                      "orderCount": ordered, "cancelCount": lost, "buyoutCount": buyout, "orderSum": 999999}}}


def wb_realization(rid=1, operation="Продажа", day="2026-10-01"):
    return {"rrdId": rid, "reportId": 2259007199254740993, "reportType": 1, "nmId": 101,
            "vendorCode": "item-a", "quantity": 3 if operation == "Продажа" else 1,
            "docTypeName": operation, "sellerOperName": operation,
            "orderDt": day+"T10:00:00+03:00", "saleDt": day+"T11:00:00+03:00", "rrDate": day,
            "srid": "purchase-"+str(rid), "shkId": 1000+rid, "retailAmount": 999999}


def yandex_order(context, **changes):
    result = {"orderId": 9001, "campaignId": context["campaignId"], "fake": False, "sourcePlatform": "MARKET",
              "creationDate": context["from"]+"T10:00:00+03:00", "status": "PARTIALLY_RETURNED",
              "items": [{"id": 1, "offerId": "item-a", "offerName": "Изделие A", "count": 5,
                         "itemStatuses": [{"status": "DELIVERED_TO_BUYER", "count": 3},
                                          {"status": "RETURNED", "count": 1}, {"status": "REJECTED", "count": 1}],
                         "prices": {"total": 999999}}],
              "delivery": {"address": {"street": "buyer-data-must-not-survive"}}}
    result.update(changes)
    return result


def yandex_return(context, **changes):
    result = {"id": 8001, "orderId": 9001, "returnType": "RETURN", "shipmentStatus": "FULFILMENT_RECEIVED",
              "refundStatus": "REFUNDED", "fastReturn": False, "creationDate": context["from"]+"T12:00:00+03:00",
              "updateDate": context["from"]+"T13:00:00+03:00", "items": [{"shopSku": "item-a", "count": 1,
                  "instances": [], "price": 999999}], "buyer": {"name": "buyer-data-must-not-survive"}}
    result.update(changes)
    return result


def response_for(template_id, request, context=None):
    """Return one documented success shape, including all compound stages."""
    c = context_for(template_id) if context is None else context
    stage, body, params = request["stage"], request.get("json") or {}, request.get("params") or {}
    day = c.get("from") or "2026-10-01"
    payload = None
    if template_id == "OZ-01":
        payload = {"roles": [{"name": "Admin", "methods": ["/v1/roles"]}]}
    elif template_id == "WB-01":
        payload = {"sid": "test-seller-uuid", "name": "Тестовый продавец", "tradeMark": "Тест"}
    elif template_id == "YM-01":
        payload = ({"status": "OK", "result": {"apiKey": {"authScopes": ["all-methods:read-only"]}}}
                   if stage == "identity" else {"campaigns": [{"id": c.get("campaignId", 123),
                    "business": {"id": c.get("businessId", 12)}, "domain": "test-shop", "placementType": "FBS", "apiAvailability": "AVAILABLE"}]})
    elif template_id == "OZ-02":
        payload = ({"result": {"items": [{"product_id": 1001, "offer_id": "item-a"}], "last_id": "", "total": 1}}
                   if stage == "list" else {"items": [{"id": 1001, "sku": 101, "offer_id": "item-a", "name": "Изделие A",
                    "description_category_id": 3, "type_id": 4, "sources": [{"sku": 101}], "price": "999999"}]})
    elif template_id == "WB-02":
        payload = {"cards": [wb_card()], "cursor": {"updatedAt": "2026-10-01T10:00:00Z", "nmID": 101, "total": 1}}
    elif template_id == "YM-02":
        payload = {"status": "OK", "result": {"offerMappings": [] if body.get("archived") else [{
            "offer": {"offerId": "item-a", "name": "Изделие A", "archived": False},
            "mapping": {"marketSku": 101, "marketCategoryId": 4}}]}}
    elif template_id == "OZ-04":
        payload = {"returns": [ozon_return()], "has_next": False}
    elif template_id == "OZ-05":
        payload = {"result": posting(stage.upper(), day, posting_number=c.get("posting_number", "111111-0001-1"))}
    elif template_id == "OZ-06":
        payload = {"postings": [posting(stage.upper(), day)], "has_next": False, "cursor": ""}
    elif template_id == "OZ-07":
        payload = {"items": [{"product_id": 1001, "offer_id": "item-a", "stocks": [
            {"sku": 101, "type": "fbo", "present": 10, "reserved": 2}]}], "total": 1, "cursor": ""}
    elif template_id == "WB-03":
        payload = {"data": {"products": [wb_funnel(c)]}}
    elif template_id == "WB-04":
        if body.get("rrdId", 0):
            return {"status_code": 204, "headers": {}, "payload": None}
        payload = [wb_realization(day=day), wb_realization(2, "Возврат", day)]
    elif template_id == "YM-03":
        payload = {"orders": [yandex_order(c)]}
    elif template_id == "YM-04":
        payload = {"status": "OK", "result": {"returns": [yandex_return(c)]}}
    elif template_id == "YM-06" and stage.startswith("warehouses_"):
        if stage == "warehouses_current":
            warehouses = [] if c.get("warehouse_groups") else [{"id": 501, "name": "Synthetic warehouse",
                "models": [{"placementType": c["placementType"], "campaignId": c["campaignId"], "apiAvailability": "AVAILABLE"}]}]
        else:
            warehouses = [{"id": 601, "campaignId": c["campaignId"], "groupInfo": {"id": 701, "name": "Synthetic group"}}]
        payload = {"status": "OK", "result": {"warehouses": warehouses}}
    elif template_id in ("OZ-03", "WB-05", "YM-05", "YM-06"):
        if request["generate"]:
            if template_id == "OZ-03":
                scheme = body["filter"]["delivery_schema"][0].upper()
                payload = {"result": {"code": "synthetic-ozon-"+scheme}}
            elif template_id == "WB-05":
                payload = {"data": {"taskId": "synthetic-wb-task"}}
            else:
                payload = {"status": "OK", "result": {"reportId": "synthetic-yandex-"+template_id}}
        elif stage == "poll":
            if template_id == "OZ-03":
                rid = body["code"]
                payload = {"result": {"code": rid, "status": "success", "file": "https://cdn1.ozone.ru/s3/reports/"+rid+".csv"}}
            elif template_id == "WB-05":
                payload = {"data": {"id": "synthetic-wb-task", "status": "done"}}
            else:
                payload = {"status": "OK", "result": {"status": "DONE", "file": "https://storage.yandexcloud.net/test-quantity/"+template_id+".zip"}}
        elif stage == "download":
            if template_id == "OZ-03":
                return {"status_code": 200, "headers": {"content-type": "text/csv"},
                        "content": ozon_csv("FBS" if "FBS" in request["url"] else "FBO", day)}
            if template_id == "WB-05":
                payload = [{"nmId": 101, "vendorCode": "item-a", "barcode": "111", "warehouses": [
                    {"warehouseName": "Всего находится на складах", "quantity": 10},
                    {"warehouseName": "Коледино", "quantity": 10},
                    {"warehouseName": "В пути до получателей", "quantity": 2}]}]
            else:
                raw = yandex_realization_zip(day) if template_id == "YM-05" else yandex_stocks_zip(c.get("placementType") in ("FBY", "LAAS"), not c.get("warehouse_groups"), c.get("placementType", "FBS"))
                return {"status_code": 200, "headers": {"content-type": "application/zip"}, "content": raw}
    if payload is None:
        raise AssertionError("Missing synthetic documented shape for "+template_id+":"+stage)
    return {"status_code": 200, "headers": {}, "payload": deepcopy(payload)}


def success_sequence(template_id, context=None):
    """Materialize requests and response fixtures through the real pure adapter."""
    from platform_core import market_quantity_providers as p
    c = context_for(template_id) if context is None else dict(context)
    checkpoint, cases = {}, []
    for _ in range(30):
        req = p.request(template_id, checkpoint, c)
        response = response_for(template_id, req, c)
        out = p.consume(template_id, checkpoint, c, response)
        cases.append({"request": req, "response": response, "outcome": out})
        checkpoint = out["checkpoint"]
        if out["complete"]:
            return cases
        c["now"] = max(c["now"]+1, out.get("next_due") or 0)
    raise AssertionError("Fixture did not terminate for "+template_id)
