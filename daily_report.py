import requests
import json
from datetime import date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

FB_ACCESS_TOKEN   = os.environ["FB_ACCESS_TOKEN"]
FB_NEW_ACCOUNT_ID = os.environ["FB_NEW_ACCOUNT_ID"]
FB_OLD_ACCOUNT_ID = os.environ["FB_OLD_ACCOUNT_ID"]
SHOPIFY_STORE     = os.environ["SHOPIFY_STORE"]
SHOPIFY_TOKEN     = os.environ["SHOPIFY_TOKEN"]
GOOGLE_CUSTOMER_ID      = os.environ["GOOGLE_CUSTOMER_ID"]
GOOGLE_DEV_TOKEN        = os.environ["GOOGLE_DEV_TOKEN"]
GOOGLE_REFRESH_TOKEN    = os.environ["GOOGLE_REFRESH_TOKEN"]
GOOGLE_CLIENT_ID        = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET    = os.environ["GOOGLE_CLIENT_SECRET"]
SENDER_EMAIL      = os.environ["SENDER_EMAIL"]
SENDER_PASSWORD   = os.environ["SENDER_PASSWORD"]
RECIPIENT_EMAIL   = os.environ["RECIPIENT_EMAIL"]
FB_NEW_UTM        = os.environ["FB_NEW_UTM"]
FB_OLD_UTM        = os.environ["FB_OLD_UTM"]

yesterday   = date.today() - timedelta(days=1)
report_date = yesterday.strftime("%-d %B %Y")
date_str    = yesterday.strftime("%Y-%m-%d")

def get_fb_spend(account_id):
    url = f"https://graph.facebook.com/v20.0/{account_id}/insights"
    params = {
        "fields": "spend",
        "time_range": json.dumps({"since": date_str, "until": date_str}),
        "access_token": FB_ACCESS_TOKEN
    }
    resp = requests.get(url, params=params).json()
    if resp.get("data"):
        return float(resp["data"][0].get("spend", 0))
    return 0.0

def get_google_access_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": GOOGLE_REFRESH_TOKEN,
        "grant_type":    "refresh_token"
    }).json()
    return resp["access_token"]

def get_google_spend():
    access_token = get_google_access_token()
    url = f"https://googleads.googleapis.com/v17/customers/{GOOGLE_CUSTOMER_ID}/googleAds:searchStream"
    headers = {
        "Authorization":   f"Bearer {access_token}",
        "developer-token": GOOGLE_DEV_TOKEN,
        "Content-Type":    "application/json"
    }
    query = f"""
        SELECT metrics.cost_micros FROM campaign
        WHERE segments.date = '{date_str}' AND campaign.status = 'ENABLED'
    """
    resp = requests.post(url, headers=headers, json={"query": query})
    total = sum(
        int(row.get("metrics", {}).get("costMicros", 0))
        for batch in resp.json()
        for row in batch.get("results", [])
    )
    return total / 1_000_000

def get_shopify_orders():
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/orders.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    params = {
        "status": "any",
        "created_at_min": f"{date_str}T00:00:00+05:30",
        "created_at_max": f"{date_str}T23:59:59+05:30",
        "limit": 250,
        "fields": "id,total_price,source_name"
    }
    all_orders, next_url = [], url
    while next_url:
        resp = requests.get(next_url, headers=headers, params=params)
        all_orders.extend(resp.json().get("orders", []))
        link = resp.headers.get("Link", "")
        next_url, params = None, {}
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    next_url = part.split(";")[0].strip().strip("<>")
    return all_orders

def summarise(orders, source):
    if source == "organic":
        matched = [o for o in orders if not o.get("source_name") or o.get("source_name","").lower() in ["web","direct",""]]
    else:
        matched = [o for o in orders if (o.get("source_name") or "").lower() == source.lower()]
    return round(sum(float(o["total_price"]) for o in matched), 2), len(matched)

def roi(value, spend):
    return round(value / spend, 2) if spend else 0.0

def fmt(n):
    return f"Rs. {n:,.2f}"

fb_new_spend = get_fb_spend(FB_NEW_ACCOUNT_ID)
fb_old_spend = get_fb_spend(FB_OLD_ACCOUNT_ID)
google_spend = get_google_spend()
all_orders   = get_shopify_orders()

fb_new_value, fb_new_count   = summarise(all_orders, FB_NEW_UTM)
fb_old_value, fb_old_count   = summarise(all_orders, FB_OLD_UTM)
google_value, google_count   = summarise(all_orders, "google")
organic_value, organic_count = summarise(all_orders, "organic")

total_spend  = round(fb_new_spend + fb_old_spend + google_spend, 2)
total_value  = round(fb_new_value + fb_old_value + google_value + organic_value, 2)
total_orders = fb_new_count + fb_old_count + google_count + organic_count

body = f"""Dear Sir,

Kindly find below the stats for {report_date}:

FACEBOOK - NEW ACCOUNT

Ads Spend - {fmt(fb_new_spend)}
Orders Value - {fmt(fb_new_value)}
No. Of Orders - {fb_new_count}
ROI - {roi(fb_new_value, fb_new_spend)}

FACEBOOK - OLD ACCOUNT

Ads Spend - {fmt(fb_old_spend)}
Orders Value - {fmt(fb_old_value)}
No. Of Orders - {fb_old_count}
ROI - {roi(fb_old_value, fb_old_spend)}

GOOGLE ADS

Ads Spend - {fmt(google_spend)}
Orders Value - {fmt(google_value)}
No. Of Orders - {google_count}
ROI - {roi(google_value, google_spend)}

ORGANIC

Orders Value - {fmt(organic_value)}
No. Of Orders - {organic_count}

TOTAL

Ads Spend - {fmt(total_spend)}
Orders Value - {fmt(total_value)}
No. Of Orders - {total_orders}
ROI - {roi(total_value, total_spend)}

Regards,
Sanjana"""

msg = MIMEMultipart()
msg["From"]    = SENDER_EMAIL
msg["To"]      = RECIPIENT_EMAIL
msg["Subject"] = f"Daily Ads vs Revenue Report — {report_date}"
msg.attach(MIMEText(body, "plain"))

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
    print(f"Report sent for {report_date}")
