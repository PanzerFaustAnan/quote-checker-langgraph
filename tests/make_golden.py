"""Writes tests/golden/*.json: the hand-checked correct extraction for each sample PDF.

I typed these in by reading each PDF. They are used to:
  - test the rules and the pipeline without an API key;
  - measure how accurately the AI reads the documents (evaluate.py --fields).
Run: python tests/make_golden.py
"""
import json
from pathlib import Path


def item(code, desc, qty, unit, price, amount, row):
    return dict(item_code=code, description=desc, quantity=qty, unit=unit, unit_price=price, amount=amount, quote=row)


def pack(supplier, qno, date, it, sub, vat, total, tin, bin_, payment, delivery, penalty, validity,
         vat_rate=15, incl_vat=False):
    return {
        "supplier_name": {"value": supplier, "quote": f"For {supplier}"},
        "quotation_no": {"value": qno, "quote": f"Quotation no. {qno}"},
        "quote_date": {"value": date, "quote": f"Date {date}"},
        "pr_reference": {"value": "PR-2026-114", "quote": "Reference PR-2026-114"},
        "items": [it],
        "subtotal": {"value": sub, "quote": f"Subtotal {sub:,.2f}" if sub is not None else None},
        "vat_rate_percent": {"value": vat_rate if vat is not None else None, "quote": f"VAT 15% {vat:,.2f}" if vat else None},
        "vat_amount": {"value": vat, "quote": f"VAT 15% {vat:,.2f}" if vat else None},
        "total": {"value": total, "quote": f"Total {total:,.2f}" if not incl_vat else f"Total (all taxes included) {total:,.2f}"},
        "prices_include_vat": incl_vat,
        "tin": {"value": tin, "quote": f"TIN: {tin}" if tin else None},
        "bin": {"value": bin_, "quote": f"BIN: {bin_}" if bin_ else None},
        "payment": payment,
        "delivery": delivery,
        "penalty": penalty,
        "validity_days": {"value": validity, "quote": f"valid for {validity} days from the date above"},
    }


def pay(adv, lo, hi, quote, frm="delivery", clear=True):
    return dict(advance_percent=adv, balance_days_min=lo, balance_days_max=hi, counted_from=frm, is_clear=clear, quote=quote)


def dlv(n, quote, unit="days"):
    return dict(number=n, unit=unit, quote=quote)


def pen(pct, quote, order_value=True):
    return dict(present=True, percent=pct, per="week", basis_is_order_value=order_value, quote=quote)


NO_PENALTY = dict(present=False, percent=None, per=None, basis_is_order_value=None, quote=None)

PACKS = {
    "supplier-pack-01": pack(
        "Padma Textile Mills Ltd", "QT-2026-901", "2026-10-21",
        item("A", "Cotton twill fabric, 280 gsm", 12000, "metre", 472.00, 5664000.00,
             "A Cotton twill fabric, 280 gsm 12,000 metre 472.00 5,664,000.00"),
        5664000.00, 849600.00, 6513600.00, "101458013391", "000170141-0101",
        pay(10, 45, 45, "10% advance payable with the purchase order. Balance payable within 45 days after delivery and acceptance of goods."),
        dlv(24, "Delivery within 24 days of receiving the purchase order."),
        pen(1, "Late delivery penalty: 1% of order value for each full week of delay."), 45),
    "supplier-pack-02": pack(
        "Jamuna Trims and Accessories", "QT-2026-902", "2026-10-22",
        item("B", "Metal zipper, 18 cm", 20000, "piece", 36.00, 720000.00,
             "B Metal zipper, 18 cm 20,000 piece 36.00 720,000.00"),
        720000.00, 108000.00, 828000.00, "102458023391", "000270241-0101",
        pay(0, 30, 30, "No advance payment required. Full payment within 30 days of delivery."),
        dlv(21, "Goods will be delivered at your factory within 21 days from the date of PO."),
        pen(0.75, "For late delivery the supplier shall pay 0.75% of the order value per week of delay."), 30),
    "supplier-pack-03": pack(
        "Karnaphuli Yarn Traders", "QT-2026-903", "2026-10-23",
        item("C", "Polyester sewing thread, cone", 800, "cone", 229.00, 183200.00,
             "C Polyester sewing thread, cone 800 cone 229.00 183,200.00"),
        183200.00, 27480.00, 210680.00, "103458033391", "000370341-0101",
        pay(15, 40, 40, "15% advance payable with the purchase order. Balance within 40 days of delivery."),
        dlv(20, "Delivery within 20 days of PO."),
        pen(0.5, "Delay in delivery will attract a penalty of 0.5% of order value per week."), 30),
    "supplier-pack-04": pack(
        "Surma Packaging Industries", "QT-2026-904", "2026-10-24",
        item("D", "Poly bag, 30 x 40 cm", 50000, "piece", 6.65, 332500.00,
             "D Poly bag, 30 x 40 cm 50,000 piece 6.65 332,500.00"),
        332500.00, 49875.00, 382375.00, "104458043391", "000470441-0101",
        pay(10, 30, 30, "10% advance payable with the purchase order. Payment within 30 days after delivery."),
        dlv(28, "Delivery within 28 days of PO."),
        pen(0.6, "Late delivery penalty of 0.6% of order value per week."), 40),
    "supplier-pack-05": pack(
        "Meghna Carton Works", "QT-2026-905", "2026-10-25",
        item("E", "Carton box, 5-ply", 3000, "piece", 92.00, 276000.00,
             "E Carton box, 5-ply 3,000 piece 92.00 276,000.00"),
        276000.00, 41400.00, 317400.00, "105458053391", "000570541-0101",
        pay(40, 30, 30, "40% advance payable with the purchase order. 40% advance with the purchase order, balance 60% within 30 days of delivery.",
            clear=False),
        dlv(25, "Delivery within 25 days of PO."),
        pen(1, "Late delivery penalty of 1% of order value per week."), 30),
    "supplier-pack-06": pack(
        "Teesta Fabrics Ltd", "QT-2026-906", "2026-10-26",
        item("A", "Cotton twill fabric, 280 gsm", 12000, "metre", 465.00, 5580000.00,
             "A Cotton twill fabric, 280 gsm 12,000 metre 465.00 5,580,000.00"),
        5580000.00, 837000.00, 6417000.00, "106458063391", "000670641-0101",
        pay(10, 60, 60, "10% advance payable with the purchase order. Balance within 60 days of delivery."),
        dlv(27, "Delivery within 27 days of PO."),
        NO_PENALTY, 30),
    "supplier-pack-07": pack(
        "Rupsha Zipper Factory", "QT-2026-907", "2026-10-20",
        item("B", "Metal zipper, 18 cm", 16500, "piece", 35.00, 577500.00,
             "B Metal zipper, 18 cm 16,500 piece 35.00 577,500.00"),
        577500.00, 86625.00, 664125.00, "107458073391", "000770741-0101",
        pay(0, 45, 45, "No advance payment required. Payment within 45 days of delivery."),
        dlv(22, "Delivery within 22 days of PO."),
        pen(0.5, "Late delivery penalty: 0.5% of order value per week."), 35),
    "supplier-pack-08": pack(
        "Bhairab Thread and Co", "QT-2026-908", "2026-10-21",
        item("C", "Polyester sewing thread, cone", 800, "cone", 205.00, 164000.00,
             "C Polyester sewing thread, cone 800 cone 205.00 164,000.00"),
        164000.00, 24600.00, 188600.00, None, None,
        pay(10, 30, 30, "10% advance payable with the purchase order. Payment within 30 days of delivery."),
        dlv(18, "Delivery within 18 days of PO."),
        pen(0.5, "Late delivery penalty of 0.5% per week of delay.", order_value=False), 30),
    "supplier-pack-09": pack(
        "Dhaleshwari Poly Pack", "QT-2026-909", "2026-10-22",
        item("D", "Poly bag, 30 x 40 cm", 50000, "piece", 6.40, 322000.00,
             "D Poly bag, 30 x 40 cm 50,000 piece 6.40 322,000.00"),
        322000.00, 48300.00, 370300.00, "109458093391", "000970941-0101",
        pay(5, 30, 90, "5% advance payable with the purchase order. Payment within 30 to 90 days as agreed by both parties.",
            frm="unclear", clear=False),
        dlv(4, "Delivery within 4 weeks of PO.", unit="weeks"),
        pen(0.5, "Late delivery penalty of 0.5% of order value per week."), 30),
    "supplier-pack-10": pack(
        "Kushiyara Box Industries", "QT-2026-910", "2026-10-23",
        item("E", "Carton box, 5-ply", 3000, "piece", 94.00, 282000.00,
             "E Carton box, 5-ply 3,000 piece 94.00 282,000.00"),
        None, None, 282000.00, "110458103391", "001071041-0101",
        pay(10, 45, 45, "10% advance payable with the purchase order. Payment within 45 days of delivery."),
        dlv(60, "Delivery within 60 days of PO."),
        pen(0.5, "Late delivery penalty of 0.5% of order value per week."), 30, incl_vat=True),
}

if __name__ == "__main__":
    out = Path(__file__).parent / "golden"
    out.mkdir(exist_ok=True)
    for name, data in PACKS.items():
        (out / f"{name}.json").write_text(json.dumps(data, indent=2))
    print(f"Wrote {len(PACKS)} files to {out}")
