"""Minimal example: prevent an invoice email from being sent twice."""

from kiwai import Kiwai

kiwai = Kiwai("example-state.db")


@kiwai.idempotent(key=lambda invoice_id: f"invoice-email:{invoice_id}")
def send_invoice_email(invoice_id: int) -> dict[str, object]:
    print(f"Sending invoice {invoice_id}...")
    return {"invoice_id": invoice_id, "sent": True}


if __name__ == "__main__":
    print(send_invoice_email(23068))
    print(send_invoice_email(23068))
