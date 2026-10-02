"""Curated seed universe (reference metadata only; prices/fundamentals always come from providers).
Sectors for ETFs are broad category labels assigned manually; stock sectors come from SEC SIC data."""

STOCKS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "BAC", "XOM", "CVX", "JNJ",
          "PFE", "UNH", "PG", "KO", "PEP", "WMT", "COST", "HD", "DIS", "NFLX", "INTC", "CSCO", "V", "MA"]
ETFS = {
    "SPY": ("SPDR S&P 500 ETF Trust", "US large-cap equity"),
    "QQQ": ("Invesco QQQ Trust", "US large-cap growth equity"),
    "IWM": ("iShares Russell 2000 ETF", "US small-cap equity"),
    "DIA": ("SPDR Dow Jones Industrial Average ETF", "US large-cap equity"),
    "VTI": ("Vanguard Total Stock Market ETF", "US total-market equity"),
    "EFA": ("iShares MSCI EAFE ETF", "International developed equity"),
    "EEM": ("iShares MSCI Emerging Markets ETF", "Emerging-market equity"),
    "TLT": ("iShares 20+ Year Treasury Bond ETF", "Long-term Treasuries"),
    "IEF": ("iShares 7-10 Year Treasury Bond ETF", "Intermediate Treasuries"),
    "LQD": ("iShares iBoxx $ Investment Grade Corporate Bond ETF", "Investment-grade credit"),
    "HYG": ("iShares iBoxx $ High Yield Corporate Bond ETF", "High-yield credit"),
    "GLD": ("SPDR Gold Shares", "Gold"),
    "SLV": ("iShares Silver Trust", "Silver"),
    "XLK": ("Technology Select Sector SPDR Fund", "US equity - Technology"),
    "XLF": ("Financial Select Sector SPDR Fund", "US equity - Financials"),
    "XLE": ("Energy Select Sector SPDR Fund", "US equity - Energy"),
    "XLV": ("Health Care Select Sector SPDR Fund", "US equity - Health Care"),
    "XLP": ("Consumer Staples Select Sector SPDR Fund", "US equity - Consumer Staples"),
    "XLU": ("Utilities Select Sector SPDR Fund", "US equity - Utilities"),
}
INDICES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq Composite", "^DJI": "Dow Jones Industrial Average",
           "^RUT": "Russell 2000", "^VIX": "CBOE Volatility Index"}
