from playwright.sync_api import sync_playwright
import time

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Show browser so you can see it too
        context = browser.new_context()
        page = context.new_page()

        # Capture all console messages
        console_messages = []
        def handle_console(msg):
            text = msg.text
            console_messages.append({
                'type': msg.type,
                'text': text,
                'timestamp': time.time()
            })
            print(f"[{msg.type.upper()}] {text}")

        page.on('console', handle_console)

        # Capture network requests to port 12394
        network_requests = []
        def handle_request(request):
            if '12394' in request.url:
                print(f"\n[NETWORK REQUEST] {request.method} {request.url}")
                network_requests.append({'type': 'request', 'url': request.url, 'method': request.method})

        def handle_response(response):
            if '12394' in response.url:
                print(f"[NETWORK RESPONSE] {response.status} {response.url}")
                network_requests.append({'type': 'response', 'url': response.url, 'status': response.status})

        page.on('request', handle_request)
        page.on('response', handle_response)

        print("\n" + "="*80)
        print("OPENING BROWSER - Navigate to http://localhost:3000")
        print("="*80 + "\n")

        page.goto('http://localhost:3000', timeout=60000)

        print("\n" + "="*80)
        print("WAITING 30 SECONDS FOR CONNECTION...")
        print("="*80 + "\n")

        page.wait_for_timeout(30000)

        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        print(f"\nTotal console messages: {len(console_messages)}")
        print(f"Total network requests to 12394: {len(network_requests)}")

        # Check for connection status
        connected = any('Connected:' in msg['text'] for msg in console_messages)
        error = any('Connection' in msg['text'] and 'error' in msg['text'].lower() for msg in console_messages)

        print(f"\nConnection status: {'CONNECTED' if connected else 'NOT CONNECTED'}")
        if error:
            print("Errors detected in console")

        # Check network requests
        if network_requests:
            print(f"\nNetwork activity detected:")
            for req in network_requests[:10]:  # Show first 10
                print(f"  {req['type'].upper()}: {req.get('method', '')} {req.get('url', '')} - {req.get('status', '')}")

        print("\n" + "="*80)
        print("Press Enter to close browser...")
        print("="*80)

        input()

        browser.close()

if __name__ == '__main__':
    main()
