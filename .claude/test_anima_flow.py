"""
Test Anima complete flow - connect to frontend, send message, verify LLM logging
"""

from playwright.sync_api import sync_playwright, Page
import time
import sys
import io

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def test_anima_flow():
    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Navigate to frontend
        print("Navigating to frontend...")
        page.goto('http://localhost:3000')
        page.wait_for_load_state('networkidle')

        # Take screenshot of initial state
        page.screenshot(path='/tmp/anima_initial.png', full_page=True)
        print("Screenshot saved: /tmp/anima_initial.png")

        # Wait for Socket.IO connection
        print("Waiting for Socket.IO connection...")
        page.wait_for_timeout(3000)

        # Capture console logs
        console_messages = []
        def on_console(msg):
            console_messages.append({
                'type': msg.type,
                'text': msg.text,
            })
            if msg.type == 'error':
                print(f"[Console Error] {msg.text}")
            elif 'socket' in msg.text.lower() or 'connect' in msg.text.lower():
                print(f"[Console] {msg.text}")

        page.on('console', on_console)

        # Look for text input or send button
        print("Looking for input elements...")

        # Try to find input/send button elements
        try:
            # Check if page has loaded
            content = page.content()
            print(f"Page loaded, length: {len(content)}")

            # Try multiple selectors for the input
            input_selectors = [
                'input[placeholder*="输入"]',
                'input[placeholder*="消息"]',
                'input[type="text"]',
                'textarea',
                '[contenteditable="true"]',
                '.input',
            ]

            input_elem = None
            for selector in input_selectors:
                try:
                    elem = page.locator(selector).first
                    if elem.count() > 0:
                        print(f"Found input with selector: {selector}")
                        input_elem = elem
                        break
                except:
                    continue

            # Look for send button
            send_button = page.locator('button[type="submit"], button:has-text("发送"), button:has-text("Send")').first
            print(f"Send buttons found: {send_button.count()}")

            # If we have an input, try to send a message
            if input_elem and input_elem.count() > 0:
                print("Found input element")

                # Check if input is disabled
                is_disabled = input_elem.is_disabled()
                print(f"Input disabled: {is_disabled}")

                if is_disabled:
                    print("Input is disabled, looking for microphone button to stop listening...")

                    # Try to find and click the microphone button
                    mic_button = page.locator('button:has-text("Mic"), button:has-text("录音"), button[aria-label*="mic"], button[aria-label*="录音"]').first

                    if mic_button.count() > 0:
                        print("Found microphone button, clicking to stop recording...")
                        mic_button.click()
                        page.wait_for_timeout(1000)
                    else:
                        print("No microphone button found, waiting for status to change...")
                        page.wait_for_timeout(5000)

                # Clear and type a test message
                test_message = "你好，请介绍一下自己"
                input_elem.click()
                page.wait_for_timeout(500)
                input_elem.fill(test_message)
                print(f"Typed message: {test_message}")

                # Wait a bit
                page.wait_for_timeout(1000)

                # Look for send button and click it
                if send_button.count() > 0:
                    send_button.click()
                    print("Clicked send button")
                else:
                    # Try pressing Enter
                    input_elem.press('Enter')
                    print("Pressed Enter")

                # Wait for response
                print("Waiting for LLM response...")
                page.wait_for_timeout(15000)

                # Take screenshot of response
                page.screenshot(path='/tmp/anima_response.png', full_page=True)
                print("Screenshot saved: /tmp/anima_response.png")

            else:
                print("No input element found, checking page structure...")

                # Print page structure for debugging
                body_text = page.locator('body').inner_text()
                print(f"Body text preview: {body_text[:500]}...")

        except Exception as e:
            print(f"Error during interaction: {e}")
            import traceback
            traceback.print_exc()

        # Print console logs
        print("\n=== Console Logs ===")
        for msg in console_messages[-20:]:  # Last 20 messages
            print(f"  [{msg['type']}] {msg['text']}")

        # Check browser logs
        print("\n=== Browser WebSocket connections ===")
        # Try to get WebSocket info from page
        try:
            # Look for any WebSocket activity in performance or network logs
            print("Checking for WebSocket activity...")
        except:
            pass

        # Keep browser open for a bit to see the result
        print("\nKeeping browser open for 10 seconds for manual inspection...")
        page.wait_for_timeout(10000)

        browser.close()
        print("\nTest completed!")

if __name__ == '__main__':
    test_anima_flow()
