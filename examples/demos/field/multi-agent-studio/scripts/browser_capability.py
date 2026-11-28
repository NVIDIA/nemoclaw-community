# SPDX-License-Identifier: Apache-2.0

"""Shared capability boundary for browser requests in chat and collaboration."""
BROWSER_LIMIT = (
    'This demo has no tool to open or control the user PC browser or an interactive browser session. '
    'web_fetch (or HTTP requests through curl) only retrieves public page text; it cannot open a visible window, '
    'click, log in, operate a shopping cart, or interact with a site. '
    'When the user explicitly asks to open/control a browser (for example: open my browser, go to Amazon '
    'and find laundry products), explain this missing capability FIRST, in the user language. '
    'Do not silently reinterpret that request as public-page research, delegate a fetch attempt, or try guessed '
    'URLs to simulate browser control. Offer a clearly labeled alternative such as a link the user can open '
    'or public-page research, and wait for the user to choose it before performing the substitute research. '
    'If the user already explicitly accepted public-page research instead, proceed within the available tools. '
    'Ordinary requests to research the web or summarize a URL do not require browser control and should proceed. '
    'Never claim that a browser was opened or interacted with. '
    'When authorized public-page research fails with an access denial, login requirement, CAPTCHA or rate limit, '
    'report the observed cause and stop that blocked route; do not repeatedly fetch the same site or alternate '
    'URLs to bypass it. Do not infer a specific cause from an unspecified fetch failure. '
)
