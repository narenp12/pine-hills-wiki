//! Browser connection + page fetching over the Chrome DevTools Protocol.
//!
//! Two modes (both reuse YOUR logged-in session — no Yahoo key, no 2FA toggle):
//! * `--user-data-dir <path>`: launch Chrome with a persistent profile dir.
//! * `--connect <url>`: attach to a Chrome you started with
//!   `--remote-debugging-port=9222` (recommended: you log in once in that
//!   Chrome, then point the scraper at it).
//!
//! If neither is given we launch a fresh ephemeral Chromium (you'd need to log
//! in interactively the first time; not recommended for Yahoo).
//!
//! Resource hygiene: every page opened by `fetch_page` is closed before it
//! returns, and `connect_browser` is always paired with `close` via a `finally`
//! guard in `main`, so neither Chrome tabs nor the browser process leak.

use anyhow::{Context, Result};
use chromiumoxide::browser::{Browser, BrowserConfig};
use chromiumoxide::Page;
use futures::StreamExt;
use std::path::PathBuf;
use std::time::Duration;

use crate::Cli;

/// Hard ceiling for connecting/launching and for individual page fetches, so a
/// missing Chrome binary or a closed debug port fails fast instead of hanging
/// the whole run forever.
const CONNECT_TIMEOUT: Duration = Duration::from_secs(30);
const PAGE_TIMEOUT: Duration = Duration::from_secs(60);

/// Resolve a Chrome CDP endpoint to its WebSocket debugger URL.
///
/// Accepts either a `ws://`/`wss://` URL directly, or the HTTP debugger
/// endpoint (e.g. `http://127.0.0.1:9222`) — for the HTTP form we fetch
/// `/json/version` and read `webSocketDebuggerUrl`, which is what
/// `chromiumoxide::Browser::connect` actually requires.
async fn resolve_ws_endpoint(endpoint: &str) -> Result<String> {
    if endpoint.starts_with("ws://") || endpoint.starts_with("wss://") {
        return Ok(endpoint.to_string());
    }
    let base = endpoint.trim_end_matches('/');
    let version_url = format!("{base}/json/version");
    let client = reqwest::Client::builder()
        .timeout(CONNECT_TIMEOUT)
        .build()
        .context("failed to build HTTP client for CDP endpoint resolution")?;
    let resp = client
        .get(&version_url)
        .send()
        .await
        .map_err(|e| anyhow::anyhow!("could not reach Chrome HTTP debugger at {version_url}: {e}"))?;
    let v: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| anyhow::anyhow!("invalid /json/version response from Chrome: {e}"))?;
    v.get("webSocketDebuggerUrl")
        .and_then(|s| s.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| {
            anyhow::anyhow!(
                "/json/version did not contain webSocketDebuggerUrl — is --remote-debugging-port set on this Chrome?"
            )
        })
}

/// Launch or connect to a browser and return a handle to drive pages.
///
/// The CDP event-loop handler is spawned in a task. A non-fatal handler error
/// (e.g. an `UnknownError` for a single command) is logged and skipped with
/// `continue` — breaking out would kill the browser's event loop and make every
/// subsequent CDP call (new_page/content/close) hang.
pub async fn connect_browser(cli: &Cli) -> Result<Browser> {
    // Mode 1: attach to an already-running Chrome via CDP.
    if let Some(endpoint) = &cli.connect {
        // chromiumoxide::Browser::connect needs the WebSocket debugger URL
        // (ws://...). The user may pass either that or the plain HTTP debugger
        // endpoint (http://127.0.0.1:9222); resolve the latter via /json/version.
        let ws = resolve_ws_endpoint(endpoint).await?;
        println!(">> connecting to Chrome at {ws}");
        let (browser, handler) = tokio::time::timeout(
            CONNECT_TIMEOUT,
            Browser::connect(ws),
        )
        .await
        .map_err(|_| anyhow::anyhow!("timed out connecting to Chrome after {CONNECT_TIMEOUT:?}"))?
        .map_err(|e| anyhow::anyhow!("failed to connect to Chrome: {e}"))?;
        spawn_handler(handler);
        return Ok(browser);
    }

    // Mode 2: launch with a persistent user-data-dir (your real profile).
    let mut builder = BrowserConfig::builder();
    if let Some(chrome) = &cli.chrome {
        builder = builder.chrome_executable(chrome.clone());
    }
    if let Some(udd) = &cli.user_data_dir {
        builder = builder.user_data_dir(udd.clone());
    }
    if cli.dump.is_some() {
        builder = builder.with_head(); // visual mode helps with manual login/debug
    } else {
        builder = builder.no_sandbox(); // typical for automation on Linux/macOS
    }

    println!(
        ">> launching Chromium (persistent session: {})",
        cli.user_data_dir.is_some()
    );
    let (browser, handler) = tokio::time::timeout(
        CONNECT_TIMEOUT,
        Browser::launch(builder.build().map_err(|e| anyhow::anyhow!(e))?),
    )
    .await
    .map_err(|_| {
        anyhow::anyhow!("timed out launching Chromium after {CONNECT_TIMEOUT:?}; is the Chrome binary present?")
    })?
    .context("failed to launch Chromium")?;
    spawn_handler(handler);
    Ok(browser)
}

/// Drive the CDP event-loop handler to completion; tolerate non-fatal errors.
fn spawn_handler(mut handler: chromiumoxide::Handler) {
    tokio::spawn(async move {
        while let Some(event) = handler.next().await {
            if let Err(e) = event {
                eprintln!("   (cdp handler) non-fatal error: {e}");
                // Continue: a single bad event must not kill the event loop,
                // or every later CDP command would hang.
            }
        }
    });
}

/// Open a page, navigate, wait for JS render, return the rendered HTML.
///
/// The page is explicitly closed before returning so tabs don't accumulate
/// across the (up to 40) dataset/season fetches.
pub async fn fetch_page(
    browser: &Browser,
    url: &str,
    dump: &Option<PathBuf>,
    tag: &str,
) -> Result<String> {
    // `new_page(url)` already performs the initial navigation, so calling
    // `wait_for_navigation()` afterwards races an already-completed load and
    // can hang. Instead let the page settle, then poll until the rendered
    // body has actual content (Yahoo is JS-heavy, so the initial HTML shell
    // is near-empty until scripts run).
    let page = tokio::time::timeout(PAGE_TIMEOUT, browser.new_page(url))
        .await
        .map_err(|_| anyhow::anyhow!("timed out opening {url} after {PAGE_TIMEOUT:?}"))??;
    let html = wait_for_content(&page).await?;

    if let Some(dir) = dump {
        std::fs::create_dir_all(dir)?;
        let path = dir.join(format!("{tag}.html"));
        std::fs::write(&path, &html)?;
        println!("   dumped -> {}", path.display());
    }

    // Close the tab now so we don't leak it; ignore a close error (the content
    // we need is already captured).
    let _ = tokio::time::timeout(PAGE_TIMEOUT, page.close()).await;
    Ok(html)
}

/// Poll the page until its serialized HTML is non-trivial (JS has rendered),
/// with a hard timeout so we never hang forever on a blank/blocked page.
async fn wait_for_content(page: &Page) -> Result<String> {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(30);
    loop {
        let html = page.content().await?;
        // A real Yahoo page has a <body> with substantial markup; the pre-render
        // shell is tiny. 4000 bytes is a safe floor for "something rendered".
        if html.len() > 4000 || tokio::time::Instant::now() >= deadline {
            return Ok(html);
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

/// Convenience: close the browser (needs &mut). Safe to call once.
pub async fn close(browser: &mut Browser) -> Result<()> {
    browser.close().await?;
    Ok(())
}
