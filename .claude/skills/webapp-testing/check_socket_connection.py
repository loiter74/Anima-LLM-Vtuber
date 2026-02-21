from playwright.sync_api import sync_playwright
import sys

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
                'location': f"{msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}"
            })

        page.on('console', handle_console)

        # Navigate to the frontend
        print("Navigating to http://localhost:3000...")
        page.goto('http://localhost:3000', wait_until='networkidle', timeout=10000)

        # Wait a bit for Socket.IO connection attempts
        page.wait_for_timeout(3000)

        # Print console messages
        print("\n=== Browser Console Logs ===")
        if console_messages:
            for msg in console_messages:
                print(f"[{msg['type'].upper()}] {msg['text']}")
                if msg['location']:
                    print(f"  Location: {msg['location']}")
        else:
            print("No console messages captured")

        # Check page title
        print(f"\nPage title: {page.title()}")

        # Check for Socket.IO connection status in the DOM
        try:
            # Look for connection status indicator
            status_elements = page.locator('[data-testid="connection-status"], .connection-status').all()
            if status_elements:
                print("\n=== Connection Status Elements ===")
                for el in status_elements:
                    print(f"Status element text: {el.text_content()}")
        except Exception as e:
            print(f"Could not find connection status elements: {e}")

        # Take a screenshot for visual inspection
        page.screenshot(path='C:/Users/30262/Project/Anima/frontend_screenshot.png', full_page=True)
        print("\nScreenshot saved to: frontend_screenshot.png")

        browser.close()

if __name__ == '__main__':
    main()
