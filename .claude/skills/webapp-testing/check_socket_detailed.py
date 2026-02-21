from playwright.sync_api import sync_playwright
import time

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Capture console logs
        console_messages = []
        def handle_console(msg):
            console_messages.append({
                'type': msg.type,
                'text': msg.text,
            })
            print(f"[{msg.type.upper()}] {msg.text}")

        page.on('console', handle_console)

        # Capture network requests
        network_requests = []
        def handle_request(request):
            if 'socket.io' in request.url or '12394' in request.url:
                print(f"[REQUEST] {request.method} {request.url}")
                network_requests.append({
                    'url': request.url,
                    'method': request.method,
                })

        def handle_response(response):
            if 'socket.io' in response.url or '12394' in response.url:
                print(f"[RESPONSE] {response.status} {response.url}")
                network_requests.append({
                    'url': response.url,
                    'status': response.status,
                })

        page.on('request', handle_request)
        page.on('response', handle_response)

        # Navigate to the frontend
        print("\n=== Navigating to http://localhost:3000 ===")
        page.goto('http://localhost:3000', wait_until='networkidle', timeout=10000)

        # Wait for connection to establish
        print("\n=== Waiting 10 seconds for Socket.IO connection... ===")
        page.wait_for_timeout(10000)

        # Check connection status
        print("\n=== Checking connection status ===")
        connected = page.evaluate("""
          () => {
            // Check if window.socketService exists and its status
            if (window.socketService) {
              return window.socketService.getStatus();
            }
            return 'socketService not found';
          }
        """)
        print(f"Connection status: {connected}")

        # Check connectionStore state
        store_state = page.evaluate("""
          () => {
            // Try to access Zustand store
            if (window.useConnectionStore) {
              return window.useConnectionStore.getState();
            }
            return 'useConnectionStore not found on window';
          }
        """)
        print(f"Connection store state: {store_state}")

        browser.close()

if __name__ == '__main__':
    main()
