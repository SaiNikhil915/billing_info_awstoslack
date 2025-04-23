import boto3
import json
import os
import logging
import requests
from datetime import datetime, date, timedelta
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from fpdf import FPDF

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# S3 Bucket to Store PDF Reports
S3_BUCKET = "billingbktlambda11"
S3_CLIENT = boto3.client("s3")

# Slack Webhook URL (Stored in AWS Lambda environment variable)
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
# Slack API Token for file uploads
SLACK_API_TOKEN = os.getenv("SLACK_API_TOKEN")
# Slack Channel ID
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "general")

# Get AWS Cost Explorer Client
ce_client = boto3.client("ce", region_name="us-east-1")
# Get AWS Account ID
sts_client = boto3.client('sts')

def get_last_month_dates():
    """Dynamically calculate last month's start and end date."""
    today = date.today()
    first_day = date(today.year, today.month - 1, 1) if today.month > 1 else date(today.year - 1, 12, 1)
    last_day = date(today.year, today.month, 1) - timedelta(days=1)
    return first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d")

class BillingReportPDF(FPDF):
    """Enhanced PDF class with header and footer capabilities."""
    def __init__(self, organization_id=None, organization_name=None):
        super().__init__()
        self.organization_id = organization_id or "AWS Organization"
        self.organization_name = organization_name or "AWS Organization"
        self.report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def header(self):
        # Logo - AWS blue rectangle as a logo placeholder
        self.set_fill_color(30, 65, 100)  # AWS blue-like color
        self.rect(10, 10, 30, 10, 'F')
        self.set_text_color(255, 255, 255)
        self.set_font('Arial', 'B', 10)
        self.set_xy(10, 10)
        self.cell(30, 10, 'AWS Report', 0, 0, 'C')
        self.set_text_color(0, 0, 0)
        
        # Report Title
        self.set_font('Arial', 'B', 16)
        self.set_xy(50, 10)
        self.cell(100, 10, 'AWS Billing Report', 0, 0, 'C')
        
        # Date and Organization Info
        self.set_font('Arial', '', 8)
        self.set_xy(160, 8)
        self.cell(40, 5, f'Generated: {self.report_date}', 0, 2, 'R')
        self.cell(40, 5, f'Organization ID: {self.organization_id}', 0, 2, 'R')
        self.cell(40, 5, f'Name: {self.organization_name}', 0, 0, 'R')
        
        # Line break after header
        self.ln(20)
    
    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", 'I', size=8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')
        self.set_x(10)
        self.cell(0, 10, 'Confidential - For Internal Use Only', 0, 0, 'L')
    
    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.set_fill_color(200, 220, 255)
        self.cell(0, 10, title, 0, 1, 'L', 1)
        self.ln(5)
    
    def cost_summary(self, total_cost, currency="USD"):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, f"Total Cost: {currency} {total_cost:.2f}", 0, 1, 'L')
        self.ln(5)
    
    def create_table(self, headers, data, col_widths=None, highlight_top=False):
        # Set default column widths if not provided
        if col_widths is None:
            col_widths = [self.w / len(headers) - 10] * len(headers)
        
        # Table headers with color
        self.set_font('Arial', 'B', 10)
        self.set_fill_color(66, 133, 244)  # Blue header
        self.set_text_color(255, 255, 255)  # White text
        
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 8, header, 1, 0, 'C', 1)
        self.ln()
        
        # Table data
        self.set_font('Arial', '', 10)
        self.set_text_color(0, 0, 0)  # Black text
        
        # Alternate row colors and highlight top account
        for index, row in enumerate(data):
            # Highlight the top spending account in gold
            if index == 0 and highlight_top:
                self.set_fill_color(255, 215, 0)  # Gold color for highest spender
            elif index % 2 == 0:
                self.set_fill_color(240, 240, 240)  # Light gray
            else:
                self.set_fill_color(255, 255, 255)  # White
            
            # Make the account ID bold for better visibility
            if highlight_top:
                self.set_font('Arial', 'B' if index == 0 else '', 10)
            
            for i, cell in enumerate(row):
                align = 'R' if isinstance(cell, (int, float)) or (isinstance(cell, str) and cell.replace('.', '', 1).isdigit()) else 'L'
                self.cell(col_widths[i], 7, str(cell), 1, 0, align, 1)
            self.ln()
            
            # Reset font
            self.set_font('Arial', '', 10)

def fetch_aws_organization_details():
    """Fetch AWS organization details."""
    try:
        account_info = sts_client.get_caller_identity()
        account_id = account_info.get('Account', 'Unknown')
        
        # Try to get organization details if available
        org_client = boto3.client('organizations')
        try:
            org_details = org_client.describe_organization()
            org_id = org_details.get('Organization', {}).get('Id', 'Unknown')
            
            # Try to get organization name from master account
            org_name = org_client.describe_account(AccountId=org_details.get('Organization', {}).get('MasterAccountId', account_id)).get('Account', {}).get('Name', 'AWS Organization')
            
            return org_id, org_name
        except:
            return account_id, "AWS Organization"  # Default if organizations access not available
            
    except Exception as e:
        logger.warning(f"Could not retrieve organization details: {e}")
        return "Unknown", "AWS Organization"

def fetch_aws_account_names():
    """Fetch account names for the accounts in the organization."""
    account_names = {}
    try:
        org_client = boto3.client('organizations')
        paginator = org_client.get_paginator('list_accounts')
        
        for page in paginator.paginate():
            for account in page.get('Accounts', []):
                account_names[account.get('Id')] = account.get('Name')
                
    except Exception as e:
        logger.warning(f"Could not retrieve account names: {e}")
    
    return account_names

def fetch_billing_data():
    """Fetches AWS cost breakdown per account and service for the last month, plus forecast."""
    start_date, end_date = get_last_month_dates()
    logger.info(f"Fetching billing data from {start_date} to {end_date}")
    
    # Calculate forecast period (current month)
    today = date.today()
    forecast_start = date(today.year, today.month, 1).strftime("%Y-%m-%d")
    forecast_end = (date(today.year, today.month + 1, 1) if today.month < 12 
                   else date(today.year + 1, 1, 1)).strftime("%Y-%m-%d")
    
    try:
        # Get total cost
        total_response = ce_client.get_cost_and_usage(
            TimePeriod={'Start': start_date, 'End': end_date},
            Granularity='MONTHLY',
            Metrics=['UnblendedCost']
        )
        
        total_cost = float(total_response['ResultsByTime'][0]['Total']['UnblendedCost']['Amount'])
        currency = total_response['ResultsByTime'][0]['Total']['UnblendedCost']['Unit']
        
        # Get account breakdown
        account_response = ce_client.get_cost_and_usage(
            TimePeriod={'Start': start_date, 'End': end_date},
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            GroupBy=[{"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}]
        )
        
        cost_breakdown = []
        for result in account_response.get("ResultsByTime", []):
            for group in result.get("Groups", []):
                account_id = group["Keys"][0]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                cost_breakdown.append({"AccountID": account_id, "Cost": cost})
        
        # Sort by cost (highest first)
        cost_breakdown.sort(key=lambda x: x["Cost"], reverse=True)
        
        # Get service breakdown
        service_response = ce_client.get_cost_and_usage(
            TimePeriod={'Start': start_date, 'End': end_date},
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}]
        )
        
        service_breakdown = []
        for result in service_response.get("ResultsByTime", []):
            for group in result.get("Groups", []):
                service_name = group["Keys"][0]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                service_breakdown.append({"ServiceName": service_name, "Cost": cost})
        
        # Sort by cost (highest first)
        service_breakdown.sort(key=lambda x: x["Cost"], reverse=True)
        
        # Get cost forecast
        try:
            forecast_response = ce_client.get_cost_forecast(
                TimePeriod={
                    'Start': forecast_start,
                    'End': forecast_end
                },
                Metric='AMORTIZED_COST',
                Granularity='MONTHLY'
            )
            
            forecast_cost = float(forecast_response.get('Total', {}).get('Amount', 0.0))
            forecast_currency = forecast_response.get('Total', {}).get('Unit', 'USD')

            
            # Calculate month-over-month change
            mom_change = ((forecast_cost - total_cost) / total_cost) * 100 if total_cost > 0 else 0
            
        except Exception as e:
            logger.warning(f"Could not get forecast data: {e}")
            forecast_cost = 0.0
            forecast_currency = currency
            mom_change = 0.0
        
        return {
            "total_cost": total_cost,
            "currency": currency,
            "cost_breakdown": cost_breakdown,
            "service_breakdown": service_breakdown,
            "forecast_cost": forecast_cost,
            "forecast_currency": forecast_currency,
            "mom_change": mom_change,
            "start_date": start_date, 
            "end_date": end_date,
            "forecast_start": forecast_start,
            "forecast_end": forecast_end
        }
        
    except NoCredentialsError:
        logger.error("AWS credentials not found.")
    except PartialCredentialsError:
        logger.error("Incomplete AWS credentials provided.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    
    return {
        "total_cost": 0.0,
        "currency": "USD",
        "cost_breakdown": [],
        "service_breakdown": [],
        "forecast_cost": 0.0,
        "forecast_currency": "USD",
        "mom_change": 0.0,
        "start_date": start_date,
        "end_date": end_date,
        "forecast_start": forecast_start,
        "forecast_end": forecast_end
    }

def format_slack_message(billing_data, account_names=None):
    """Formats billing data into a structured Slack message with all content in tabular format."""
    if account_names is None:
        account_names = {}
    
    total_cost = billing_data["total_cost"]
    cost_breakdown = billing_data["cost_breakdown"]
    service_breakdown = billing_data["service_breakdown"]
    forecast_cost = billing_data["forecast_cost"]
    mom_change = billing_data["mom_change"]
    
    # Determine trend indicators
    trend_icon = "🔴" if mom_change > 0 else "🟢" if mom_change < 0 else "⚪"
    trend_text = f"(+{mom_change:.1f}%)" if mom_change > 0 else f"({mom_change:.1f}%)" if mom_change < 0 else "(0%)"
    
    message = (
    "==================================================\n"
    "||          $$$$ AWS COST OPTIMIZATION REPORT $$$$         ||\n"
    "==================================================\n\n"
    )

    
    # Summary table with billing period, total cost and forecast
    message += "```\n"
    message += "SUMMARY\n"
    message += "----------------------------------------------------------------\n"
    message += f"Billing Period       | {billing_data['start_date']} to {billing_data['end_date']}\n"
    message += f"Total AWS Cost       | ${total_cost:.2f}\n"
    message += f"Forecast (Current)   | ${forecast_cost:.2f} {trend_icon} {trend_text}\n"
    message += "----------------------------------------------------------------\n```\n\n"
    
    
    # Top AWS Accounts table
    message += "*Top AWS Accounts:*\n```\n"
    message += "  Account ID    |  Account Name  |  Cost (USD)  |  % of Total  \n"
    message += "----------------------------------------------------------------\n"

    # Limit to top 5 accounts for cleaner message
    for index, item in enumerate(cost_breakdown[:5]):
        account_id = item['AccountID']
        account_name = account_names.get(account_id, 'Unknown')
        if len(account_name) > 12:
            account_name = account_name[:9] + "..."
        percentage = (item['Cost'] / total_cost) * 100 if total_cost else 0
        
        # Add ranking emojis
        message += f" {account_id[:12]}  | {account_name.ljust(12)} | ${item['Cost']:10.2f} | {percentage:10.1f}%\n"

    message += "----------------------------------------------------------------\n```\n\n"

    # Key Insights table
    message += "*Key Insights:*\n```\n"
    message += "METRIC                        | VALUE\n"
    message += "----------------------------------------------------------------\n"
    
    if cost_breakdown:
        highest_spender = cost_breakdown[0]
        highest_name = account_names.get(highest_spender['AccountID'], 'Unknown')
        message += f"Highest Spending Account    | {highest_spender['AccountID']} - {highest_name}\n"
        message += f"                            | ${highest_spender['Cost']:.2f}\n"
        
        if len(cost_breakdown) > 1:
            lowest_spender = cost_breakdown[-1]
            lowest_name = account_names.get(lowest_spender['AccountID'], 'Unknown')
            message += f"Lowest Spending Account     | {lowest_spender['AccountID']} - {lowest_name}\n"
            message += f"                            | ${lowest_spender['Cost']:.2f}\n"
    
    # Add top service insight
    if service_breakdown:
        top_service = service_breakdown[0]
        service_percent = (top_service['Cost'] / total_cost) * 100 if total_cost > 0 else 0
        message += f"Highest Cost Service        | {top_service['ServiceName']}\n"
        message += f"                            | ${top_service['Cost']:.2f} ({service_percent:.1f}% of total)\n"
    
    # Add month-over-month trend insight
    if mom_change != 0:
        trend_direction = "increase" if mom_change > 0 else "decrease"
        message += f"Month-over-Month Trend      | {abs(mom_change):.1f}% {trend_direction}\n"
    
    message += "----------------------------------------------------------------\n```"

    return message

def send_to_slack(message, pdf_path=None, s3_url=None):
    """Sends the formatted message and PDF to Slack via Webhook or API."""
    if not SLACK_WEBHOOK_URL:
        logger.error("SLACK_WEBHOOK_URL is not set in environment variables.")
        return False

    # If we have a PDF file to share
    if pdf_path and s3_url:
        # If we have a Slack API token, try to upload the file directly
        if SLACK_API_TOKEN:
            logger.info(f"Attempting to upload PDF to Slack channel: {SLACK_CHANNEL_ID}")
            try:
                # Upload file directly to Slack
                with open(pdf_path, 'rb') as file:
                    files = {'file': file}
                
                    response = requests.post(
                        'https://slack.com/api/files.upload',
                        files=files,
                        data={
                            'token': SLACK_API_TOKEN,
                            'channels': SLACK_CHANNEL_ID,
                            'initial_comment': message,
                            'title': os.path.basename(pdf_path),
                            'filename': os.path.basename(pdf_path)
                        }
                    )
                
                if response.status_code == 200:
                    json_response = response.json()
                    if json_response.get('ok', False):
                        logger.info("✅ Message and PDF successfully sent to Slack.")
                        return True
                    else:
                        logger.error(f"❌ Slack API error: {json_response.get('error', 'Unknown error')}")
                else:
                    logger.error(f"❌ HTTP error uploading to Slack: {response.status_code}")
            
            except Exception as e:
                logger.error(f"❌ Exception when uploading PDF to Slack: {str(e)}")
        
        # If direct upload failed or we don't have an API token, add a link to the S3 URL
        logger.info("Adding S3 URL to Slack message")
        message += f"\n\n*📊 <{s3_url}|Click here to download the PDF Report>*"
    
    # Send message through webhook
    try:
        payload = {"text": message}
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)

        if response.status_code == 200:
            logger.info("✅ Message successfully sent to Slack.")
            return True
        else:
            logger.error(f"❌ Failed to send message to Slack. Status code: {response.status_code}, Response: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Exception when sending message to Slack: {str(e)}")
        return False

def generate_pdf_report(billing_data, org_id, org_name, account_names=None):
    """Generate an enhanced PDF billing report with forecast and service breakdown."""
    if account_names is None:
        account_names = {}
        
    pdf = BillingReportPDF(org_id, org_name)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Billing period information with better styling
    pdf.set_font("Arial", style='B', size=14)
    pdf.set_fill_color(30, 65, 100)  # AWS blue
    pdf.set_text_color(255, 255, 255)  # White text
    pdf.cell(0, 10, "Monthly Billing Summary", 0, 1, 'C', 1)
    
    pdf.set_text_color(0, 0, 0)  # Reset text color
    pdf.set_font("Arial", style='B', size=11)
    pdf.cell(0, 8, f"Billing Period: {billing_data['start_date']} to {billing_data['end_date']}", 0, 1, 'C')
    pdf.ln(5)

    # Total cost summary with visually appealing badge
    pdf.set_fill_color(245, 245, 245)  # Light gray background
    pdf.set_draw_color(30, 65, 100)  # AWS blue border
    pdf.rect(20, pdf.get_y(), 170, 25, 'FD')
    pdf.set_font("Arial", style='B', size=16)
    pdf.set_xy(25, pdf.get_y() + 8)
    pdf.cell(160, 10, f"Total Cost: {billing_data['currency']} {billing_data['total_cost']:.2f}", 0, 1, 'C')
    pdf.ln(10)
    
    # Add forecast information
    pdf.set_font("Arial", style='B', size=14)
    pdf.cell(0, 10, "Cost Forecast", 0, 1, 'L')
    
    # Create a forecast box with trend indicator
    pdf.set_fill_color(240, 248, 255)  # Alice blue
    pdf.set_draw_color(70, 130, 180)  # Steel blue
    pdf.set_fill_color(240, 248, 255)  # Alice blue
    pdf.rect(20, pdf.get_y(), 170, 50, 'F')  # Just fill
    pdf.set_draw_color(0, 0, 0)  # Black border
    pdf.rect(20, pdf.get_y(), 170, 50, 'D') 
    
    # Forecast amount
    pdf.set_font("Arial", style='B', size=12)
    pdf.set_xy(25, pdf.get_y() + 5)
    pdf.cell(160, 8, f"Current Month Forecast: {billing_data['forecast_currency']} {billing_data['forecast_cost']:.2f}", 0, 2)
    
    # Month-over-month change
    mom_change = billing_data['mom_change']
    # Replace Unicode arrow symbols with ASCII alternatives
    trend_icon = "^" if mom_change > 0 else "v" if mom_change < 0 else "-"
    trend_color = (255, 0, 0) if mom_change > 0 else (0, 128, 0) if mom_change < 0 else (0, 0, 0)
    
    pdf.set_text_color(*trend_color)
    pdf.cell(160, 8, f"Month-over-Month Change: {trend_icon} {abs(mom_change):.1f}%", 0, 2)
    pdf.set_text_color(0, 0, 0)  # Reset text color
    
    # Continue with the rest of the function as before...
    
    # Forecast period
    pdf.set_font("Arial", style='', size=10)
    pdf.cell(160, 8, f"Forecast Period: {billing_data['forecast_start']} to {billing_data['forecast_end']}", 0, 1)
    pdf.ln(15)

    # Account breakdown with highlighting for top accounts
    pdf.chapter_title("Cost by AWS Account")
    
    if billing_data["cost_breakdown"]:
        # Prepare table data
        headers = ["Account ID", "Account Name", "Cost", "% of Total"]
        data = []
        
        # Get account data for table
        for item in billing_data["cost_breakdown"]:
            account_id = item['AccountID']
            account_name = account_names.get(account_id, 'Unknown')
            percentage = (item["Cost"] / billing_data["total_cost"]) * 100 if billing_data["total_cost"] > 0 else 0
            data.append([
                account_id,
                account_name,
                f"{billing_data['currency']} {item['Cost']:.2f}",
                f"{percentage:.1f}%"
            ])
            
        # Set column widths
        col_widths = [50, 70, 35, 35]
        pdf.create_table(headers, data, col_widths, highlight_top=True)
        
        # Add key insights section
        pdf.ln(10)
        pdf.chapter_title("Account Highlights")
        
        # Highest spending account highlight
        highest = billing_data["cost_breakdown"][0]
        highest_name = account_names.get(highest['AccountID'], 'Unknown')
        pdf.set_fill_color(255, 215, 0)  # Gold
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(0, 10, "Highest Spending Account", 0, 1, 'L')
        pdf.set_font("Arial", '', 10)
        
        # Create highlighted box for highest spending account
        pdf.set_fill_color(255, 250, 205)  # Light yellow background
        pdf.set_draw_color(255, 215, 0)  # Gold border
        pdf.rect(20, pdf.get_y(), 170, 25, 'FD')
        pdf.set_xy(25, pdf.get_y() + 5)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(160, 5, f"Account ID: {highest['AccountID']}", 0, 2)
        pdf.cell(160, 5, f"Name: {highest_name}", 0, 2)
        pdf.cell(160, 5, f"Cost: {billing_data['currency']} {highest['Cost']:.2f}", 0, 1)
        pdf.ln(15)
        
        # Lowest spending account if there are more than one account
        if len(billing_data["cost_breakdown"]) > 1:
            lowest = billing_data["cost_breakdown"][-1]
            lowest_name = account_names.get(lowest['AccountID'], 'Unknown')
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(0, 10, "Lowest Spending Account", 0, 1, 'L')
            pdf.set_font("Arial", '', 10)
            
            # Create highlighted box for lowest spending account
            pdf.set_fill_color(240, 255, 240)  # Light green background
            pdf.set_draw_color(46, 139, 87)  # Sea green border
            pdf.rect(20, pdf.get_y(), 170, 25, 'FD')
            pdf.set_xy(25, pdf.get_y() + 5)
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(160, 5, f"Account ID: {lowest['AccountID']}", 0, 2)
            pdf.cell(160, 5, f"Name: {lowest_name}", 0, 2)
            pdf.cell(160, 5, f"Cost: {billing_data['currency']} {lowest['Cost']:.2f}", 0, 1)
    else:
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 10, "No billing data available for this period.", 0, 1, 'C')
    
    # Service breakdown on second page
    pdf.add_page()
    pdf.chapter_title("Cost by AWS Service")
    
    if billing_data["service_breakdown"]:
        # Create a pie chart-like visual (simplified)
        top_services = billing_data["service_breakdown"][:5]  # Top 5 services
        others_cost = sum(item["Cost"] for item in billing_data["service_breakdown"][5:])
        
        if others_cost > 0:
            top_services.append({"ServiceName": "Other Services", "Cost": others_cost})
        
        # Visual representation of top services
        start_y = pdf.get_y()
        colors = [
            (70, 130, 180),   # Steel Blue
            (100, 149, 237),  # Cornflower Blue
            (135, 206, 235),  # Sky Blue
            (176, 224, 230),  # Powder Blue
            (173, 216, 230),  # Light Blue
            (211, 211, 211)   # Light Gray (for Others)
        ]
        
        # Service breakdown table
        headers = ["Service", "Cost", "% of Total"]
        data = []

        total_cost = billing_data["total_cost"]
        for i, item in enumerate(top_services):
            percentage = (item["Cost"] / total_cost) * 100 if total_cost > 0 else 0
            
            color_index = min(i, len(colors) - 1)
            service_name = item["ServiceName"]
            if len(service_name) > 30:
                service_name = service_name[:27] + "..."
                
            data.append([
                service_name,
                f"{billing_data['currency']} {item['Cost']:.2f}",
                f"{percentage:.1f}%"
            ])

        # Set column widths for service table
        col_widths = [100, 45, 45]
        pdf.create_table(headers, data, col_widths)

        # Visual representation with colored blocks
        pdf.ln(10)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Service Cost Distribution", 0, 1, 'L')

        bar_width = 160
        bar_height = 15
        start_x = 20
        legend_box_size = 10
        legend_spacing = 7

        # Draw horizontal stacked bar chart
        cumulative_percentage = 0
        for i, item in enumerate(top_services):
            percentage = (item["Cost"] / total_cost) * 100 if total_cost > 0 else 0
            segment_width = (percentage / 100) * bar_width
                
            if segment_width > 0:
                pdf.set_fill_color(*colors[min(i, len(colors) - 1)])
                pdf.rect(start_x + (cumulative_percentage / 100) * bar_width, 
                        pdf.get_y(), 
                        segment_width, 
                        bar_height, 
                        'F')
                cumulative_percentage += percentage

        # Draw border around the entire bar
        pdf.set_draw_color(0, 0, 0)
        pdf.rect(start_x, pdf.get_y(), bar_width, bar_height, 'D')
        pdf.ln(bar_height + 5)

        # Add legend with improved layout
        legend_y_position = pdf.get_y()
        legend_column_width = 120  # Increased width for each column
        max_items_per_column = (len(top_services) + 1) // 2  # Distribute items evenly

        for i, item in enumerate(top_services):
            percentage = (item["Cost"] / total_cost) * 100 if total_cost > 0 else 0
                
            # Calculate position (2-column layout)
            column = i // max_items_per_column
            row = i % max_items_per_column
                
            # Set position for this legend item
            current_x = start_x + (column * legend_column_width)
            current_y = legend_y_position + (row * legend_spacing)
            pdf.set_xy(current_x, current_y)
                
            # Draw color box
            pdf.set_fill_color(*colors[min(i, len(colors) - 1)])
            pdf.rect(current_x, current_y, legend_box_size, 5, 'F')
                
            # Add text with proper spacing
            pdf.set_font("Arial", '', 8)
            pdf.set_xy(current_x + legend_box_size + 5, current_y)
                
            # Truncate service name if too long
            service_name = item["ServiceName"]
            if len(service_name) > 30:  # Increased character limit
                service_name = service_name[:27] + "..."
                    
            pdf.cell(legend_column_width - legend_box_size - 10, 5, f"{service_name} ({percentage:.1f}%)", 0, 0)

        # Adjust final position after legend
        pdf.ln(max_items_per_column * legend_spacing + 5)


    # Cost optimization recommendations
    pdf.ln(10)
    pdf.chapter_title("Cost Optimization Recommendations")
    
    pdf.set_font("Arial", 'B', 11)
    pdf.set_fill_color(230, 247, 255)  # Light blue
    pdf.cell(0, 8, "1. Identify Idle Resources", 0, 1, 'L', 1)
    pdf.set_font("Arial", '', 10)
    pdf.multi_cell(0, 6, "Look for idle EC2 instances, unattached EBS volumes, and unused Elastic IPs which may be generating unnecessary costs across all your accounts.")
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 11)
    pdf.set_fill_color(230, 247, 255)  # Light blue
    pdf.cell(0, 8, "2. Consider Reserved Instances", 0, 1, 'L', 1)
    pdf.set_font("Arial", '', 10)
    pdf.multi_cell(0, 6, "For consistently running workloads, Reserved Instances can offer significant discounts compared to On-Demand pricing. Review your highest-cost accounts for RI opportunities.")
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 11)
    pdf.set_fill_color(230, 247, 255)  # Light blue
    pdf.cell(0, 8, "3. Use AWS Budgets and Cost Explorer", 0, 1, 'L', 1)
    pdf.set_font("Arial", '', 10)
    pdf.multi_cell(0, 6, "Set up budget alerts for each account and regularly review cost trends in AWS Cost Explorer to identify optimization opportunities.")
    pdf.ln(5)
    
    # Save PDF
    pdf_filename = f"/tmp/aws_billing_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf.output(pdf_filename)
    return pdf_filename

def upload_pdf_to_s3(pdf_filename):
    """Upload PDF report to S3 in a monthly organized folder."""
    month_folder = datetime.now().strftime('%Y-%m')
    s3_key = f"aws_billing_reports/{month_folder}/{os.path.basename(pdf_filename)}"

    try:
        logger.info(f"Uploading {pdf_filename} to S3 bucket {S3_BUCKET} at {s3_key}")
        S3_CLIENT.upload_file(pdf_filename, S3_BUCKET, s3_key)
    
        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        logger.info(f"Upload successful! File available at {s3_url}")
        return s3_url
    except Exception as e:
        logger.error(f"Failed to upload PDF to S3: {e}", exc_info=True)
        return None

def lambda_handler(event, context):
    """AWS Lambda function execution."""
    logger.info("Starting AWS billing report generation...")

    if 'Records' in event and len(event['Records']) > 0:
        # This is an SNS notification
        record = event['Records'][0]
        if 'Sns' in record:
            # Extract the message if needed
            sns_message = record['Sns'].get('Message', '{}')
            logger.info(f"Received SNS message: {sns_message}")
            # You could parse the message as JSON if it contains specific instructions
            # message_data = json.loads(sns_message)
    
    # Fetch AWS organization details
    org_id, org_name = fetch_aws_organization_details()
    logger.info(f"Generating report for Organization: {org_id} ({org_name})")
    
    # Fetch account names
    account_names = fetch_aws_account_names()
    logger.info(f"Retrieved names for {len(account_names)} accounts")

    # Fetch billing data
    billing_data = fetch_billing_data()
    
    if billing_data["total_cost"] == 0 and not billing_data["cost_breakdown"]:
        logger.warning("No billing data available for this period.")
        return {'statusCode': 200, 'body': json.dumps({'message': 'No billing data available'})}

    # Generate PDF report
    pdf_filename = generate_pdf_report(billing_data, org_id, org_name, account_names)

    # Upload PDF report to S3
    s3_url = upload_pdf_to_s3(pdf_filename)

    # Format Slack message
    slack_message = format_slack_message(billing_data, account_names)
    
    # Send Slack message with PDF
    slack_sent = send_to_slack(slack_message, pdf_filename, s3_url)

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Billing report generated and notifications sent',
            'organization_id': org_id,
            'organization_name': org_name,
            'total_cost': billing_data["total_cost"],
            'currency': billing_data["currency"],
            'billing_period': f"{billing_data['start_date']} to {billing_data['end_date']}",
            'pdf_report_url': s3_url,
            'slack_message_sent': slack_sent
        })
    }