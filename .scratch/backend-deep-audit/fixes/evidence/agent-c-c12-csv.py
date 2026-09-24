"""C-12 pre-change fixture: formula-capable custom text in CSV export."""
from __future__ import annotations
from datetime import datetime
from types import SimpleNamespace
from app.api.portfolio import export_portfolio_csv
from agent_c_fixture_support import FakeDB, run


async def main():
    now = datetime.now()
    p = SimpleNamespace(ticker="AAPL", weight=1, region="US", last_price=1, market_value=1,
                        sector="=HYPERLINK(\"bad\")", industry="+cmd", custom_name="@SUM(1,1)",
                        added_on=now, updated_on=now)
    response = await export_portfolio_csv(db=FakeDB([p]))
    print("before.csv", response.body.decode().replace("\r", "\\r").replace("\n", "\\n"))
    print("verdict=REQUIRES_FORMULA_NEUTRALIZATION")


if __name__ == "__main__":
    run(main())
