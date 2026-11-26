/**
 * BolKhata AI — Split-Screen Counter Frontend Controller (`static/app.js`)
 *
 * Features:
 * 1. WebSocket connection to `/ws/{session_id}` for full-duplex 16kHz PCM audio + JSON telemetry
 * 2. AudioWorklet microphone capture (`static/audio-processor.js`) + gapless 24kHz PCM playback queue
 * 3. Instant barge-in buffer clearing on `interrupted` or user speech start
 * 4. Live ADK Sub-Agent routing pills (`bolkhata_root`, `khata_agent`, `inventory_agent`, `collections_agent`)
 * 5. Green "Confirmed via Voice" HITL audit pill whenever `record_khata_entry` commits
 * 6. Row highlight flash on updated customer khata rows & auto-refreshing right-panel cards
 * 7. Session Reset button + Khatabook vs. BolKhata Benchmark Stopwatch
 */

(() => {
  "use strict";

  // ==========================================================================
  // STATE
  // ==========================================================================
  let sessionId = "counter_" + Math.random().toString(36).substring(2, 9);
  let ws = null;
  let isMicActive = false;

  // Web Audio Capture & Playback State
  let audioCtx = null;
  let mediaStream = null;
  let workletNode = null;
  let sourceNode = null;
  let activePlaybackSources = [];
  let nextPlayTime = 0;
  const GEMINI_OUTPUT_SAMPLE_RATE = 24000;

  // Dashboard snapshot for diffing customer balances & flashing rows
  let previousCustomerBalances = new Map();

  // Benchmark Stopwatch State
  let benchmarkRunning = false;
  let benchmarkStartTime = 0;
  let benchmarkElapsedMs = 0;
  let benchmarkIntervalId = null;

  // ==========================================================================
  // DOM ELEMENTS
  // ==========================================================================
  const storeNameLabel = document.getElementById("storeNameLabel");
  const storeUpiChip = document.getElementById("storeUpiChip");
  const connectionLed = document.getElementById("connectionLed");
  const latencyText = document.getElementById("latencyText");
  const bargeInText = document.getElementById("bargeInText");

  const orbWrapper = document.getElementById("orbWrapper");
  const micToggleBtn = document.getElementById("micToggleBtn");
  const orbActionText = document.getElementById("orbActionText");
  const orbStatusCaption = document.getElementById("orbStatusCaption");

  const quickPromptForm = document.getElementById("quickPromptForm");
  const quickPromptInput = document.getElementById("quickPromptInput");

  const transcriptFeed = document.getElementById("transcriptFeed");
  const transcriptEmpty = document.getElementById("transcriptEmpty");

  const resetSessionBtn = document.getElementById("resetSessionBtn");
  const benchmarkDisplay = document.getElementById("benchmarkDisplay");
  const benchmarkToggleBtn = document.getElementById("benchmarkToggleBtn");
  const benchmarkResetBtn = document.getElementById("benchmarkResetBtn");

  const lastSyncBadge = document.getElementById("lastSyncBadge");
  const manualRefreshBtn = document.getElementById("manualRefreshBtn");

  const kpiTotalCredit = document.getElementById("kpiTotalCredit");
  const kpiTxCount = document.getElementById("kpiTxCount");
  const kpiTotalPayments = document.getElementById("kpiTotalPayments");
  const kpiTotalOutstanding = document.getElementById("kpiTotalOutstanding");
  const kpiCustomerCount = document.getElementById("kpiCustomerCount");

  const khataCountBadge = document.getElementById("khataCountBadge");
  const khataTableBody = document.getElementById("khataTableBody");

  const lowStockCountBadge = document.getElementById("lowStockCountBadge");
  const lowStockList = document.getElementById("lowStockList");
  const allInventoryPills = document.getElementById("allInventoryPills");

  const recSentCount = document.getElementById("recSentCount");
  const recPaidCount = document.getElementById("recPaidCount");
  const recRecoveredAmount = document.getElementById("recRecoveredAmount");
  const recRecoveryPct = document.getElementById("recRecoveryPct");
  const remindersList = document.getElementById("remindersList");

  // ==========================================================================
  // FORMATTING HELPERS
  // ==========================================================================
  function formatRupees(amount) {
    const num = Number(amount || 0);
    return "₹" + num.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  }

  function formatShortTime(isoStr) {
    if (!isoStr) return "—";
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return "Recent";
    return d.toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
    });
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ==========================================================================
  // ORB & ADK SUB-AGENT BADGE HELPERS
  // ==========================================================================
  function setOrbState(state, captionText) {
    orbWrapper.setAttribute("data-state", state);
    if (captionText) {
      orbStatusCaption.textContent = captionText;
    }
  }

  function highlightActiveAgent(agentName) {
    if (!agentName) return;
    const pills = document.querySelectorAll(".agent-pill");
    pills.forEach((pill) => {
      if (pill.dataset.agent === agentName) {
        pill.classList.add("active");
      } else {
        pill.classList.remove("active");
      }
    });
  }

  function friendlyAgentLabel(agentName) {
    const map = {
      bolkhata_root: "Root Copilot",
      khata_agent: "Khata",
      inventory_agent: "Inventory",
      collections_agent: "Collections",
    };
    return map[agentName] || agentName || "Copilot";
  }

  // ==========================================================================
  // TRANSCRIPT & HITL AUDIT PILL RENDERING
  // ==========================================================================
  let currentPartialBubble = null;
  let currentPartialRole = null;

  function appendTranscriptMessage(role, author, text, isPartial = false) {
    if (!text || !text.trim()) return;
    if (transcriptEmpty) {
      transcriptEmpty.style.display = "none";
    }

    if (author) {
      highlightActiveAgent(author);
    }

    if (currentPartialBubble && currentPartialRole === role) {
      const bodyEl = currentPartialBubble.querySelector(".msg-text");
      if (bodyEl) {
        bodyEl.textContent = text;
      }
      if (!isPartial) {
        currentPartialBubble = null;
        currentPartialRole = null;
      }
      transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
      return;
    }

    const bubble = document.createElement("div");
    bubble.className = `msg-bubble ${role === "user" ? "msg-user" : "msg-agent"}`;

    const badgeLabel = role === "user" ? "Shopkeeper" : friendlyAgentLabel(author);
    bubble.innerHTML = `
      <div class="msg-meta">
        <span class="msg-agent-badge">${escapeHtml(badgeLabel)}</span>
      </div>
      <div class="msg-text">${escapeHtml(text)}</div>
    `;

    transcriptFeed.appendChild(bubble);
    transcriptFeed.scrollTop = transcriptFeed.scrollHeight;

    if (isPartial) {
      currentPartialBubble = bubble;
      currentPartialRole = role;
    } else {
      currentPartialBubble = null;
      currentPartialRole = null;
    }
  }

  function appendToolTrace(author, toolName, payload, isResult = false) {
    if (transcriptEmpty) {
      transcriptEmpty.style.display = "none";
    }

    // Route pill based on tool name or author
    if (
      ["get_customer_balance", "record_khata_entry", "get_daily_summary"].includes(toolName)
    ) {
      highlightActiveAgent("khata_agent");
    } else if (["update_stock", "get_low_stock_items"].includes(toolName)) {
      highlightActiveAgent("inventory_agent");
    } else if (
      ["list_overdue_customers", "send_payment_reminder", "mark_reminder_paid"].includes(toolName)
    ) {
      highlightActiveAgent("collections_agent");
    } else if (author) {
      highlightActiveAgent(author);
    }

    const traceEl = document.createElement("div");
    traceEl.className = "tool-trace-item";

    const isConfirmedLedgerCommit =
      isResult &&
      toolName === "record_khata_entry" &&
      payload &&
      payload.status === "recorded";

    const confirmedPillHtml = isConfirmedLedgerCommit
      ? `<span class="confirmed-voice-pill">✓ Confirmed via Voice</span>`
      : "";

    const summaryText =
      isResult && payload && payload.message
        ? payload.message
        : `${isResult ? "Result" : "Calling"} ${toolName}()`;

    traceEl.innerHTML = `
      <span><strong>[${escapeHtml(friendlyAgentLabel(author))}]</strong> ${escapeHtml(summaryText)}</span>
      ${confirmedPillHtml}
    `;

    transcriptFeed.appendChild(traceEl);
    transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
  }

  // ==========================================================================
  // RIGHT PANEL: LIVE DASHBOARD FETCH & RENDER
  // ==========================================================================
  async function fetchDashboard(highlightCustomerName = null) {
    try {
      const resp = await fetch("/api/dashboard");
      if (!resp.ok) return;
      const data = await resp.json();
      renderDashboard(data, highlightCustomerName);
      lastSyncBadge.textContent =
        "Synced " + new Date().toLocaleTimeString("en-IN", { hour12: false });
    } catch (err) {
      console.warn("Dashboard refresh failed:", err);
    }
  }

  function renderDashboard(data, highlightCustomerName = null) {
    if (data.store_name) {
      storeNameLabel.textContent = data.store_name;
    }
    if (data.store_upi_id) {
      storeUpiChip.textContent = `UPI: ${data.store_upi_id}`;
    }

    // 1. Daily Summary KPIs
    const summary = data.daily_summary || {};
    kpiTotalCredit.textContent = formatRupees(summary.total_credit_given);
    kpiTxCount.textContent = `${summary.transaction_count || 0} recorded transactions`;
    kpiTotalPayments.textContent = formatRupees(summary.total_payments_collected);
    kpiTotalOutstanding.textContent = formatRupees(summary.total_outstanding_dues);
    kpiCustomerCount.textContent = `Across ${summary.customer_count || 0} customers`;

    // 2. Live Khata Ledger Table
    const customers = data.customers || [];
    khataCountBadge.textContent = `${customers.length} Customers`;

    if (customers.length === 0) {
      khataTableBody.innerHTML = `<tr><td colspan="4" class="table-loading">No customer records found.</td></tr>`;
    } else {
      khataTableBody.innerHTML = customers
        .map((c) => {
          const bal = Number(c.balance || 0);
          const prevBal = previousCustomerBalances.get(c.id);
          const changed =
            (prevBal !== undefined && prevBal !== bal) ||
            (highlightCustomerName &&
              c.name.toLowerCase().includes(String(highlightCustomerName).toLowerCase()));

          previousCustomerBalances.set(c.id, bal);

          let badgeClass = "balance-zero";
          if (bal >= 1000) badgeClass = "balance-high";
          else if (bal > 0) badgeClass = "balance-medium";

          return `
            <tr class="${changed ? "row-updated-flash" : ""}" data-customer-id="${escapeHtml(c.id)}">
              <td>
                <div class="customer-name-cell">
                  <span>${escapeHtml(c.name)}</span>
                </div>
              </td>
              <td>${escapeHtml(c.phone || "—")}</td>
              <td>${escapeHtml(formatShortTime(c.last_tx_at))}</td>
              <td class="text-right">
                <span class="balance-badge ${badgeClass}">${formatRupees(bal)}</span>
              </td>
            </tr>
          `;
        })
        .join("");
    }

    // 3. Low Stock Alerts & Store Inventory
    const lowStock = data.low_stock_items || [];
    lowStockCountBadge.textContent = `${lowStock.length} Alert${lowStock.length === 1 ? "" : "s"}`;

    if (lowStock.length === 0) {
      lowStockList.innerHTML = `<div class="inv-chip">All kirana items are well stocked above reorder threshold.</div>`;
    } else {
      lowStockList.innerHTML = lowStock
        .map(
          (item) => `
          <div class="low-stock-item">
            <div>
              <div class="low-stock-name">${escapeHtml(item.item_name)}</div>
              <div class="low-stock-sub">Reorder threshold: ${item.reorder_level} ${escapeHtml(item.unit || "")}</div>
            </div>
            <span class="warning-pill">${item.quantity} ${escapeHtml(item.unit || "")} left</span>
          </div>
        `
        )
        .join("");
    }

    const inventory = data.inventory || [];
    allInventoryPills.innerHTML = inventory
      .map(
        (item) => `
        <span class="inv-chip">
          ${escapeHtml(item.item_name)}: <strong>${item.quantity} ${escapeHtml(item.unit || "")}</strong>
        </span>
      `
      )
      .join("");

    // 4. Collections Recovery Pilot Card
    const rec = data.collections_recovery || {};
    recSentCount.textContent = rec.sent_count ?? 0;
    recPaidCount.textContent = rec.paid_count ?? 0;
    recRecoveredAmount.textContent = formatRupees(rec.recovered_amount ?? 0);
    recRecoveryPct.textContent = `${rec.recovery_pct ?? 0}%`;

    const reminders = data.reminders || [];
    if (reminders.length === 0) {
      remindersList.innerHTML = `<div class="inv-chip">No payment reminders sent yet. Ask BolKhata to send a WhatsApp reminder!</div>`;
    } else {
      remindersList.innerHTML = reminders
        .map((r) => {
          const isPaid = r.status === "paid";
          return `
            <div class="reminder-row">
              <div class="reminder-info">
                <div class="reminder-title">
                  <span>${escapeHtml(r.customer_name)} — ${formatRupees(r.amount)}</span>
                  <span class="reminder-status-badge ${isPaid ? "status-paid" : "status-sent"}">
                    ${isPaid ? "PAID" : "SENT"}
                  </span>
                </div>
                <div class="reminder-msg">${escapeHtml(r.message)}</div>
              </div>
              <div class="reminder-actions">
                ${
                  r.whatsapp_url
                    ? `<a href="${escapeHtml(r.whatsapp_url)}" target="_blank" rel="noopener noreferrer" class="btn-whatsapp">
                        Open WhatsApp ↗
                       </a>`
                    : ""
                }
                <button
                  type="button"
                  class="btn-mark-paid"
                  data-reminder-id="${escapeHtml(r.id)}"
                  ${isPaid ? "disabled" : ""}
                >
                  ${isPaid ? "✓ Settled" : "Mark as Paid"}
                </button>
              </div>
            </div>
          `;
        })
        .join("");

      remindersList.querySelectorAll(".btn-mark-paid").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const remId = btn.getAttribute("data-reminder-id");
          if (!remId) return;
          btn.disabled = true;
          btn.textContent = "Settling...";
          try {
            const res = await fetch(`/api/reminders/${encodeURIComponent(remId)}/paid`, {
              method: "POST",
            });
            if (res.ok) {
              const payload = await res.json();
              appendToolTrace("collections_agent", "mark_reminder_paid", payload, true);
              await fetchDashboard(payload.customer_name);
            }
          } catch (err) {
            console.error("Failed to mark reminder paid:", err);
            btn.disabled = false;
            btn.textContent = "Mark as Paid";
          }
        });
      });
    }
  }

  // ==========================================================================
  // PCM AUDIO PLAYBACK & INSTANT BARGE-IN BUFFER CLEARING
  // ==========================================================================
  function ensureAudioContext() {
    if (!audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      audioCtx = new AudioContextClass();
    }
    if (audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    return audioCtx;
  }

  function clearAudioPlaybackQueue() {
    activePlaybackSources.forEach((src) => {
      try {
        src.stop(0);
        src.disconnect();
      } catch (_) {
        // Ignore already stopped sources
      }
    });
    activePlaybackSources = [];
    if (audioCtx) {
      nextPlayTime = audioCtx.currentTime;
    }
  }

  function playIncomingPcmBytes(arrayBuffer) {
    const ctx = ensureAudioContext();
    const int16 = new Int16Array(arrayBuffer);
    if (int16.length === 0) return;

    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0;
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, GEMINI_OUTPUT_SAMPLE_RATE);
    audioBuffer.getChannelData(0).set(float32);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    const now = ctx.currentTime;
    if (nextPlayTime < now) {
      nextPlayTime = now + 0.015;
    }

    source.start(nextPlayTime);
    nextPlayTime += audioBuffer.duration;
    activePlaybackSources.push(source);

    setOrbState("speaking", "BolKhata AI is speaking • Speak anytime to barge-in");

    source.onended = () => {
      activePlaybackSources = activePlaybackSources.filter((s) => s !== source);
      if (activePlaybackSources.length === 0) {
        if (isMicActive) {
          setOrbState("listening", "Listening live (16kHz PCM) • Speak in Hinglish or English");
        } else {
          setOrbState("idle", "Hands-free Hinglish & Indian English • 16kHz Gemini Live BIDI");
        }
      }
    };
  }

  // ==========================================================================
  // WEBSOCKET CONNECTION (`/ws/{session_id}`)
  // ==========================================================================
  function ensureWebSocket() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return ws;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/${sessionId}`;
    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      connectionLed.classList.add("online");
      bargeInText.textContent = "Barge-in: Ready";
    };

    ws.onmessage = async (event) => {
      // 1. Raw binary PCM audio stream from Gemini Live
      if (event.data instanceof ArrayBuffer) {
        playIncomingPcmBytes(event.data);
        return;
      }

      // 2. JSON telemetry events
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (_) {
        return;
      }

      switch (msg.type) {
        case "latency_metric":
          latencyText.textContent = `Response: ${msg.latency_ms} ms`;
          break;

        case "interrupted":
          clearAudioPlaybackQueue();
          bargeInText.textContent = "Barge-in: Triggered ⚡";
          setOrbState("interrupted", "Barge-in detected • Playback cleared immediately");
          setTimeout(() => {
            bargeInText.textContent = "Barge-in: Ready";
            if (isMicActive) {
              setOrbState("listening", "Listening live (16kHz PCM) • Speak in Hinglish or English");
            }
          }, 900);
          break;

        case "transcript":
          appendTranscriptMessage(
            msg.role || "agent",
            msg.author || "bolkhata_root",
            msg.text,
            Boolean(msg.partial || !msg.finished)
          );
          break;

        case "tool_call":
          appendToolTrace(msg.author, msg.name, msg.args, false);
          break;

        case "tool_result":
          appendToolTrace(msg.author, msg.name, msg.result, true);
          await fetchDashboard(msg.result && msg.result.customer_name);
          break;

        case "session_reset":
          latencyText.textContent = "Response: -- ms";
          highlightActiveAgent("bolkhata_root");
          break;

        case "error":
          appendTranscriptMessage("agent", "bolkhata_root", `⚠️ ${msg.message}`, false);
          break;

        default:
          break;
      }
    };

    ws.onclose = () => {
      connectionLed.classList.remove("online", "active");
      if (isMicActive) {
        stopMicrophone();
      }
    };

    return ws;
  }

  // ==========================================================================
  // MICROPHONE AUDIOWORKLET CAPTURE (16kHz 16-BIT PCM)
  // ==========================================================================
  async function startMicrophone() {
    try {
      const ctx = ensureAudioContext();
      ensureWebSocket();

      await ctx.audioWorklet.addModule("/static/audio-processor.js");
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      sourceNode = ctx.createMediaStreamSource(mediaStream);
      workletNode = new AudioWorkletNode(ctx, "bolkhata-pcm-processor");

      workletNode.port.onmessage = (event) => {
        const data = event.data;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        if (data.type === "pcm_chunk" && data.buffer) {
          ws.send(data.buffer);
        } else if (data.type === "vad_speech_start") {
          // Local barge-in: stop ongoing agent audio immediately when shopkeeper speaks
          if (activePlaybackSources.length > 0) {
            clearAudioPlaybackQueue();
            bargeInText.textContent = "Barge-in: Active ⚡";
          }
          ws.send(JSON.stringify({ type: "speech_start", timestamp_ms: Date.now() }));
        } else if (data.type === "vad_speech_end") {
          ws.send(JSON.stringify({ type: "speech_end", timestamp_ms: Date.now() }));
        }
      };

      sourceNode.connect(workletNode);
      isMicActive = true;
      connectionLed.classList.add("active");
      orbActionText.textContent = "Listening...";
      setOrbState("listening", "Listening live (16kHz PCM) • Speak in Hinglish or English");
    } catch (err) {
      console.error("Microphone error:", err);
      appendTranscriptMessage(
        "agent",
        "bolkhata_root",
        `Microphone access could not be started (${err.message}). You can still test using the text bar below.`,
        false
      );
    }
  }

  function stopMicrophone() {
    if (workletNode && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "speech_end", timestamp_ms: Date.now() }));
    }
    if (workletNode) {
      try {
        workletNode.disconnect();
      } catch (_) {}
      workletNode = null;
    }
    if (sourceNode) {
      try {
        sourceNode.disconnect();
      } catch (_) {}
      sourceNode = null;
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
      mediaStream = null;
    }
    isMicActive = false;
    connectionLed.classList.remove("active");
    orbActionText.textContent = "Tap to Speak";
    setOrbState("idle", "Hands-free Hinglish & Indian English • 16kHz Gemini Live BIDI");
  }

  // ==========================================================================
  // BENCHMARK STOPWATCH (KHATABOOK VS. BOLKHATA SPEED COMPARISON)
  // ==========================================================================
  function updateBenchmarkDisplay() {
    const now = performance.now();
    const totalMs = benchmarkRunning
      ? benchmarkElapsedMs + (now - benchmarkStartTime)
      : benchmarkElapsedMs;
    const secs = (totalMs / 1000).toFixed(1);
    benchmarkDisplay.textContent = secs.padStart(4, "0") + "s";
  }

  benchmarkToggleBtn.addEventListener("click", () => {
    if (!benchmarkRunning) {
      benchmarkRunning = true;
      benchmarkStartTime = performance.now();
      benchmarkToggleBtn.textContent = "Stop";
      benchmarkToggleBtn.classList.add("running");
      benchmarkIntervalId = setInterval(updateBenchmarkDisplay, 100);
    } else {
      benchmarkElapsedMs += performance.now() - benchmarkStartTime;
      benchmarkRunning = false;
      benchmarkToggleBtn.textContent = "Start";
      benchmarkToggleBtn.classList.remove("running");
      clearInterval(benchmarkIntervalId);
      updateBenchmarkDisplay();
    }
  });

  benchmarkResetBtn.addEventListener("click", () => {
    benchmarkRunning = false;
    benchmarkElapsedMs = 0;
    clearInterval(benchmarkIntervalId);
    benchmarkToggleBtn.textContent = "Start";
    benchmarkToggleBtn.classList.remove("running");
    benchmarkDisplay.textContent = "00.0s";
  });

  // ==========================================================================
  // EVENT LISTENERS & INITIALIZATION
  // ==========================================================================
  micToggleBtn.addEventListener("click", () => {
    if (isMicActive) {
      stopMicrophone();
    } else {
      startMicrophone();
    }
  });

  quickPromptForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = quickPromptInput.value.trim();
    if (!text) return;
    quickPromptInput.value = "";

    appendTranscriptMessage("user", "user", text, false);
    const socket = ensureWebSocket();
    const sendPayload = () => {
      socket.send(JSON.stringify({ type: "text", text }));
    };

    if (socket.readyState === WebSocket.OPEN) {
      sendPayload();
    } else {
      socket.addEventListener("open", sendPayload, { once: true });
    }
  });

  resetSessionBtn.addEventListener("click", () => {
    clearAudioPlaybackQueue();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "reset_session" }));
      ws.close();
    }
    sessionId = "counter_" + Math.random().toString(36).substring(2, 9);
    transcriptFeed.innerHTML = "";
    if (transcriptEmpty) {
      transcriptEmpty.style.display = "block";
      transcriptFeed.appendChild(transcriptEmpty);
    }
    latencyText.textContent = "Response: -- ms";
    highlightActiveAgent("bolkhata_root");
    ensureWebSocket();
  });

  manualRefreshBtn.addEventListener("click", () => {
    fetchDashboard();
  });

  // Initial load
  fetchDashboard();
})();
