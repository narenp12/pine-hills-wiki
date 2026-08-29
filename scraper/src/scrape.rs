//! Browser connection + page fetching over the Chrome DevTools Protocol.
//!
//! Two modes (both reuse YOUR logged-in session — no Yahoo key, no 2FA toggle):
//!   * --user-data-dir <path>  : launch Chrome with a persistent profile dir.
//!   * --connect <url>          : attach to a Chrome you started with
//!                               --remote-debugging-port=9222 (recommended:
//!                               you log in once in that Chrome, then point the
//!                               scraper at it).
//!
//! If neither is given we launch a fresh ephemeral Chromium (you'd need to log
//! in interactively the first time; not recommended for Yahoo).

use anyhow::{Context, Result};
use chromiumoxide::browser::{Browser, BrowserConfig};
use futures::StreamExt;
use std::path::PathBuf;
use std::time::Duration;

use crate::Cli;

/// Launch or connect to a browser and return a handle to drive pages.
pub async fn connect_browser(cli: &Cli) -> Result<Browser> {
    // Mode 1: attach to an already-running Chrome via CDP.
    if let Some(endpoint) = &cli.connect {
        println!(">> connecting to Chrome at {endpoint}");
        let (browser, mut handler) = Browser::connect(endpoint.clone())
            .await
            .map_err(|e| anyhow::anyhow!("failed to connect to Chrome at {endpoint}: {e}"))?;
        tokio::spawn(async move {
            while let Some(h) = handler.next().await {
                if h.is_err() {
                    break;
                }
            }
        });
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

    println!(">> launching Chromium (persistent session: {})", cli.user_data_dir.is_some());
    let (browser, mut handler) = Browser::launch(builder.build().map_err(|e| anyhow::anyhow!(e))?)
        .await
        .context("failed to launch Chromium")?;
    tokio::spawn(async move {
        while let Some(h) = handler.next().await {
            if h.is_err() {
                break;
            }
        }
    });
    Ok(browser)
}

/// Open a page, navigate, wait for JS render, return the rendered HTML.
pub async fn fetch_page(
    browser: &Browser,
    url: &str,
    dump: &Option<PathBuf>,
    tag: &str,
) -> Result<String> {
    let page = browser.new_page(url).await?;
    // Yahoo is JS-heavy; wait for navigation + a render delay.
    let _ = page.wait_for_navigation().await;
    tokio::time::sleep(Duration::from_secs(3)).await;

    let html = page.content().await?;

    if let Some(dir) = dump {
        std::fs::create_dir_all(dir)?;
        let path = dir.join(format!("{tag}.html"));
        std::fs::write(&path, &html)?;
        println!("   dumped -> {}", path.display());
    }
    Ok(html)
}

/// Convenience: close the browser (needs &mut).
pub async fn close(browser: &mut Browser) -> Result<()> {
    browser.close().await?;
    Ok(())
}
