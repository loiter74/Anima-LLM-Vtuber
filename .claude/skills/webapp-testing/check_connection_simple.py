from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Capture console logs
        console_messages = []
        def handle_console(msg):
            text = msg.text
            console_messages.append(text)
            # Print all messages
            print(f"[{msg.type.upper()}] {text}")

        page.on('console', handle_console)

        # Navigate to the frontend
        print("\n=== Navigating to http://localhost:3000 ===")
        page.goto('http://localhost:3000', timeout=30000)

        # Wait for connection or timeout
        print("\n=== Waiting 15 seconds for connection... ===")
        page.wait_for_timeout(15000)

        # Check if we got a "Connected" message
        connected = any('Connected:' in msg for msg in console_messages)
        error = any('Connection error' in msg or 'Connection timeout' in msg for msg in console_messages)

        print(f"\n=== Connection Result ===")
        if connected:
            print("[SUCCESS] Connection successful!")
        elif error:
            print("[FAILED] Connection failed")
        else:
            print("[UNKNOWN] Connection status unclear")

        # Find and print the socket ID if connected
        for msg in console_messages:
            if 'Connected:' in msg:
                print(f"Socket ID: {msg.split('Connected:')[1].strip()}")

        browser.close()

if __name__ == '__main__':
    main()
