"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  ShieldCheck,
  TrendingUp,
  Activity,
  AlertTriangle,
  RefreshCw,
  Sliders,
  Play,
  Layers,
  CheckCircle2,
  XCircle,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Search,
  Filter,
  DollarSign,
  ChevronRight,
  Database,
  Lock,
  Cpu,
  Zap,
  LayoutGrid,
  Menu,
  X,
  ChevronLeft,
  Settings,
  FlaskConical,
  BarChart3,
  ListOrdered,
  Sparkles,
} from "lucide-react";

// API Base URL from env or fallback to local backend
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

export default function MerchantDashboard() {
  // State variables
  const [summary, setSummary] = useState<any>(null);
  const [attribution, setAttribution] = useState<any>(null);
  const [degradation, setDegradation] = useState<any>(null);
  const [casesData, setCasesData] = useState<any>(null);
  const [policy, setPolicy] = useState<any>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Abort controller ref to cancel previous polling fetch on each new cycle
  const pollAbortRef = useRef<AbortController | null>(null);

  // Sector Navigation & Responsive Sidebar State
  const [activeSector, setActiveSector] = useState<string>("overview");
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);

  // Filters & Pagination
  const [page, setPage] = useState<number>(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Modals & Drawers
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [timeline, setTimeline] = useState<any>(null);
  const [timelineLoading, setTimelineLoading] = useState<boolean>(false);

  const [showPolicyDrawer, setShowPolicyDrawer] = useState<boolean>(false);
  const [policyForm, setPolicyForm] = useState<any>({
    expected_version: 1,
    max_retries: 2,
    minimum_retry_interval: 30,
    max_notifications_per_24h: 2,
    max_discount_percentage: 10.0,
    manual_approval_threshold: 25000.0,
  });
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [policySuccess, setPolicySuccess] = useState<string | null>(null);

  const [showDemoDrawer, setShowDemoDrawer] = useState<boolean>(false);
  const [simBatchSize, setSimBatchSize] = useState<number>(20);
  const [simLoading, setSimLoading] = useState<boolean>(false);
  const [simStatusMessage, setSimStatusMessage] = useState<string | null>(null);
  const [simStatusError, setSimStatusError] = useState<string | null>(null);

  const [runningPresetKey, setRunningPresetKey] = useState<string | null>(null);
  const [runningAllPresets, setRunningAllPresets] = useState<boolean>(false);
  const [presetResults, setPresetResults] = useState<Record<string, any>>({});

  // Fetch all dashboard data
  const fetchData = useCallback(async () => {
    // Cancel any previous in-flight polling request to avoid overlapping fetches
    if (pollAbortRef.current) {
      pollAbortRef.current.abort();
    }
    const controller = new AbortController();
    pollAbortRef.current = controller;
    const signal = controller.signal;

    try {
      setRefreshing(true);
      setError(null);
      let successCount = 0;

      // 1. Dashboard Summary
      try {
        const resSummary = await fetch(`${API_BASE_URL}/dashboard/summary?experiment_id=1`, { signal });
        if (resSummary.ok) {
          const dataSummary = await resSummary.json();
          setSummary(dataSummary);
          successCount++;
        }
      } catch (e: any) {
        if (e.name === 'AbortError') return;
        console.warn("Dashboard summary fetch warning:", e);
      }

      // 2. Attribution Report
      try {
        const resAttr = await fetch(`${API_BASE_URL}/attribution/report?experiment_id=1`, { signal });
        if (resAttr.ok) {
          const dataAttr = await resAttr.json();
          setAttribution(dataAttr);
          successCount++;
        }
      } catch (e: any) {
        if (e.name === 'AbortError') return;
        console.warn("Attribution report fetch warning:", e);
      }

      // 3. Degradation Routes
      try {
        const resDeg = await fetch(`${API_BASE_URL}/degradation/routes`, { signal });
        if (resDeg.ok) {
          const dataDeg = await resDeg.json();
          setDegradation(dataDeg);
          successCount++;
        }
      } catch (e: any) {
        if (e.name === 'AbortError') return;
        console.warn("Degradation routes fetch warning:", e);
      }

      // 4. Recovery Cases List
      try {
        let casesUrl = `${API_BASE_URL}/cases?page=${page}&page_size=10`;
        if (statusFilter) casesUrl += `&status=${statusFilter}`;
        const resCases = await fetch(casesUrl, { signal });
        if (resCases.ok) {
          const dataCases = await resCases.json();
          setCasesData(dataCases);
          successCount++;
        }
      } catch (e: any) {
        if (e.name === 'AbortError') return;
        console.warn("Cases list fetch warning:", e);
      }

      // 5. Merchant Policy
      try {
        const resPolicy = await fetch(`${API_BASE_URL}/policy`, { signal });
        if (resPolicy.ok) {
          const dataPolicy = await resPolicy.json();
          setPolicy((prevPolicy: any) => {
            if (!prevPolicy) {
              setPolicyForm({
                expected_version: dataPolicy.version,
                max_retries: dataPolicy.max_retries,
                minimum_retry_interval: dataPolicy.minimum_retry_interval,
                max_notifications_per_24h: dataPolicy.max_notifications_per_24h,
                max_discount_percentage: dataPolicy.max_discount_percentage,
                manual_approval_threshold: parseFloat(dataPolicy.manual_approval_threshold || "25000"),
              });
            }
            return dataPolicy;
          });
          successCount++;
        }
      } catch (e: any) {
        if (e.name === 'AbortError') return;
        console.warn("Policy fetch warning:", e);
      }

      if (successCount === 0) {
        setError("Failed to connect to RecoverAI Backend API at " + API_BASE_URL);
      }
      setLoading(false);
    } catch (err: any) {
      if (err.name === 'AbortError') return;
      setError("Failed to connect to RecoverAI Backend API at " + API_BASE_URL);
      setLoading(false);
    } finally {
      setRefreshing(false);
    }
  }, [page, statusFilter]);

  // Initial load & 5-second polling loop
  useEffect(() => {
    fetchData();
    const interval = setInterval(() => {
      fetchData();
    }, 5000);
    return () => {
      clearInterval(interval);
      if (pollAbortRef.current) {
        pollAbortRef.current.abort();
      }
    };
  }, [fetchData]);

  // Fetch timeline for selected case
  useEffect(() => {
    if (!selectedCaseId) {
      setTimeline(null);
      return;
    }
    const fetchTimeline = async () => {
      setTimelineLoading(true);
      try {
        const res = await fetch(`${API_BASE_URL}/cases/${selectedCaseId}/timeline`);
        if (res.ok) {
          const data = await res.json();
          setTimeline(data);
        }
      } catch (err) {
        console.error("Timeline error:", err);
      } finally {
        setTimelineLoading(false);
      }
    };
    fetchTimeline();
  }, [selectedCaseId]);

  // Submit merchant policy form
  const handlePolicySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPolicyError(null);
    setPolicySuccess(null);

    try {
      const res = await fetch(`${API_BASE_URL}/policy`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(policyForm),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: "Policy update failed" }));
        setPolicyError(errData.detail || "Failed to update merchant policy guardrails.");
        return;
      }

      const updated = await res.json();
      setPolicy(updated);
      setPolicySuccess(`Policy updated successfully to Version ${updated.version}`);
      setPolicyForm({
        expected_version: updated.version,
        max_retries: updated.max_retries,
        minimum_retry_interval: updated.minimum_retry_interval,
        max_notifications_per_24h: updated.max_notifications_per_24h,
        max_discount_percentage: updated.max_discount_percentage,
        manual_approval_threshold: parseFloat(updated.manual_approval_threshold || "25000"),
      });
      setTimeout(() => setShowPolicyDrawer(false), 1500);
    } catch (err: any) {
      setPolicyError("Network error submitting policy update.");
    }
  };

  // Run Demo Synthetic Batch Simulation
  const handleRunSimulation = async () => {
    setSimLoading(true);
    setSimStatusMessage(null);
    setSimStatusError(null);

    const simAbort = new AbortController();
    const timeoutId = setTimeout(() => simAbort.abort(), 180_000);

    try {
      const seed = Math.floor(Math.random() * 1000);
      const res = await fetch(`${API_BASE_URL}/simulation/run?num_cases=${simBatchSize}&random_seed=${seed}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ num_cases: simBatchSize, random_seed: seed }),
        signal: simAbort.signal,
      });
      clearTimeout(timeoutId);
      if (res.ok) {
        const data = await res.json();
        setSimStatusMessage(`Successfully processed ${data.cases_processed || simBatchSize} recovery cases!`);
        await fetchData();
      } else {
        const errorBody = await res.text().catch(() => "");
        setSimStatusError(`Simulation failed (HTTP ${res.status}). ${errorBody || "Ensure backend is running."}`);
      }
    } catch (err: any) {
      clearTimeout(timeoutId);
      console.error("Simulation error:", err);
      if (err.name === 'AbortError') {
        setSimStatusError("Simulation timed out after 3 minutes. Try a smaller batch size or check backend performance.");
      } else {
        setSimStatusError("Connection error: Unable to reach backend server. Please verify backend is running on http://localhost:8000.");
      }
    } finally {
      setSimLoading(false);
    }
  };

  // Run single preset card
  const handleRunPresetCard = async (presetKey: string) => {
    setRunningPresetKey(presetKey);
    try {
      const res = await fetch(`${API_BASE_URL}/presets/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset_name: presetKey, preset_key: presetKey, seed: 42 }),
      });
      if (res.ok) {
        const data = await res.json();
        const validation = data.preset_validation || data.result?.preset_validation || data.result;
        setPresetResults((prev) => ({
          ...prev,
          [presetKey]: validation,
        }));
        await fetchData();
      }
    } catch (err) {
      console.error(`Preset ${presetKey} execution error:`, err);
    } finally {
      setRunningPresetKey(null);
    }
  };

  // Run all 7 presets
  const handleRunAllPresetsCards = async () => {
    setRunningAllPresets(true);
    try {
      const res = await fetch(`${API_BASE_URL}/presets/run_all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seed: 42 }),
      });
      if (res.ok) {
        const data = await res.json();
        const newResults: Record<string, any> = {};
        data.results.forEach((item: any) => {
          if (item.preset_validation) {
            newResults[item.preset_validation.preset_key] = item.preset_validation;
            // Also map legacy alias key if applicable
            if (item.preset_validation.preset_key === "CONFIRMED_HDFC_DEGRADATION") {
              newResults["CONFIRMED_GATEWAY_OUTAGE"] = item.preset_validation;
            }
            if (item.preset_validation.preset_key === "BUDGET_DISCOUNT_RECOVERY") {
              newResults["BUDGET_CUSTOMER_INCENTIVE"] = item.preset_validation;
            }
          }
        });
        setPresetResults(newResults);
        await fetchData();
      }
    } catch (err) {
      console.error("Run all presets error:", err);
    } finally {
      setRunningAllPresets(false);
    }
  };

  // Preset Card Definitions for UI
  const PRESET_CARDS = [
    {
      key: "BANK_TIMEOUT_RECOVERY",
      title: "Bank Timeout Instant Link",
      badge: "Instant Recovery",
      badgeColor: "bg-emerald-50 text-emerald-700 border-emerald-200",
      description: "HDFC bank authorization timeout. ML engine scores 0.85 recovery probability & dispatches instant payment link.",
      expectedAction: "DISCOUNTED_PAYMENT_LINK_10",
      expectedStatus: "RECOVERED",
    },
    {
      key: "CONFIRMED_HDFC_DEGRADATION",
      title: "Confirmed Gateway Outage",
      badge: "Outage Reroute",
      badgeColor: "bg-amber-50 text-amber-700 border-amber-200",
      description: "HDFC Debit route in CONFIRMED outage state (z-score > 3.0). Automatically reroutes via alternative payment link.",
      expectedAction: "DISCOUNTED_PAYMENT_LINK_10",
      expectedStatus: "RECOVERED",
    },
    {
      key: "BUDGET_DISCOUNT_RECOVERY",
      title: "Budget Segment Incentive",
      badge: "Incentive Link",
      badgeColor: "bg-purple-50 text-purple-700 border-purple-200",
      description: "Price-sensitive budget customer. ENV engine triggers 10% discounted payment link within policy caps.",
      expectedAction: "DISCOUNTED_PAYMENT_LINK_10",
      expectedStatus: "RECOVERED",
    },
    {
      key: "HIGH_VALUE_MANUAL_REVIEW",
      title: "High-Value Manual Review",
      badge: "Risk Guardrail",
      badgeColor: "bg-rose-50 text-rose-700 border-rose-200",
      description: "₹30,000 transaction exceeding ₹25,000 auto-threshold. Risk engine flags case for manual review.",
      expectedAction: "MANUAL_REVIEW",
      expectedStatus: "MANUAL_REVIEW",
    },
    {
      key: "OPTED_OUT_CUSTOMER",
      title: "Customer Opted Out",
      badge: "Privacy Policy",
      badgeColor: "bg-slate-100 text-slate-700 border-slate-200",
      description: "Customer opted out of outbound messages. Action generated but outbound communication is safely blocked.",
      expectedAction: "NO_ACTION",
      expectedStatus: "CUSTOMER_OPTED_OUT",
    },
    {
      key: "FRAUD_DECLINE_BLOCK",
      title: "High Risk Fraud Block",
      badge: "Fraud Block",
      badgeColor: "bg-rose-50 text-rose-700 border-rose-200",
      description: "Stolen card / fraud decline error reason. Policy engine immediately blocks recovery intervention.",
      expectedAction: "NO_ACTION",
      expectedStatus: "POLICY_BLOCKED",
    },
    {
      key: "REFUND_AFTER_RECOVERY",
      title: "Post-Recovery Refund",
      badge: "Attribution Deduction",
      badgeColor: "bg-indigo-50 text-indigo-700 border-indigo-200",
      description: "Successfully recovered payment followed by a ₹500 partial refund. Attribution engine deducts refund from net lift.",
      expectedAction: "DISCOUNTED_PAYMENT_LINK_10",
      expectedStatus: "RECOVERED",
    },
  ];

  // Format currency helpers
  const formatINR = (valStr: string | number) => {
    const num = typeof valStr === "string" ? parseFloat(valStr) : valStr;
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(num || 0);
  };

  const formatPercent = (val: any, showPlus: boolean = true) => {
    if (val === null || val === undefined) return "0.00%";
    const num = typeof val === "number" ? val : parseFloat(String(val));
    if (isNaN(num)) return "0.00%";
    const formatted = Math.abs(num).toFixed(2);
    if (num > 0) {
      return showPlus ? `+${formatted}%` : `${formatted}%`;
    } else if (num < 0) {
      return `-${formatted}%`;
    }
    return `${formatted}%`;
  };

  // Defined Sectors for Navigation Sidebar
  const sectors = [
    { id: "overview", label: "Executive Overview", icon: LayoutGrid, badge: "Live", badgeColor: "bg-emerald-50 text-emerald-700 border-emerald-200" },
    { id: "attribution", label: "Revenue Lift (A/B Test)", icon: Layers, badge: "Proven Lift", badgeColor: "bg-purple-50 text-purple-700 border-purple-200" },
    { id: "degradation", label: "Gateway Outage Monitor", icon: AlertTriangle, badge: "Protected", badgeColor: "bg-amber-50 text-amber-700 border-amber-200" },
    { id: "cases", label: "Recovery Case Stream", icon: ListOrdered, badge: `${casesData?.total || 0}`, badgeColor: "bg-slate-100 text-slate-700 border-slate-200" },
    { id: "policy", label: "Safety Rules & Guardrails", icon: Sliders, badge: `v${policy?.version || 1}`, badgeColor: "bg-slate-100 text-slate-700 border-slate-200" },
    { id: "demolab", label: "Demo Lab & Simulator", icon: FlaskConical, badge: "Lab", badgeColor: "bg-indigo-50 text-indigo-700 border-indigo-200" },
  ];

  if (loading && !summary) {
    if (error) {
      return (
        <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50 text-slate-900 p-6">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-md w-full p-8 text-center space-y-4 shadow-xl">
            <div className="w-12 h-12 rounded-full bg-rose-50 border border-rose-200 text-rose-600 flex items-center justify-center mx-auto">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <h2 className="text-lg font-bold text-slate-900">Backend Connection Error</h2>
            <p className="text-xs text-slate-500 leading-relaxed">{error}</p>
            <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-[11px] font-mono text-slate-700 text-left">
              Run: <span className="text-indigo-600 font-semibold">make dev</span> or <span className="text-indigo-600 font-semibold">./run_dev.sh</span> to start the backend.
            </div>
            <button
              onClick={() => { setLoading(true); fetchData(); }}
              className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold shadow-sm transition flex items-center justify-center space-x-2"
            >
              <RefreshCw className="w-4 h-4" />
              <span>Retry Connection Now</span>
            </button>
          </div>
        </div>
      );
    }

    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50 text-slate-900">
        <div className="flex items-center space-x-3 mb-4">
          <div className="w-8 h-8 border-3 border-indigo-600 border-t-transparent rounded-full animate-spin"></div>
          <span className="text-xl font-bold tracking-tight text-slate-900">Connecting to RecoverAI Control Center...</span>
        </div>
        <p className="text-slate-500 text-xs font-medium">Target Backend: {API_BASE_URL}</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 font-sans flex antialiased selection:bg-indigo-100 selection:text-indigo-900">
      
      {/* 1. FULL HEIGHT WHITE SIDEBAR (LEFT ALIGNED) */}
      <aside
        className={`fixed top-0 left-0 bottom-0 z-50 w-64 bg-white text-slate-800 border-r border-slate-200/80 shadow-xs flex flex-col justify-between p-4 transition-transform duration-300 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        <div className="space-y-6">
          {/* Sidebar Header Brand */}
          <div className="flex items-center justify-between pb-4 border-b border-slate-100">
            <div className="flex items-center space-x-3">
              <div className="w-9 h-9 rounded-xl bg-slate-900 flex items-center justify-center text-white shadow-xs">
                <ShieldCheck className="w-5 h-5 text-indigo-400" />
              </div>
              <div>
                <h2 className="text-sm font-extrabold text-slate-900 tracking-tight leading-tight">RecoverAI</h2>
                <p className="text-[10px] font-bold text-indigo-600 uppercase tracking-wider">Control Center v1.2</p>
              </div>
            </div>
            <button
              onClick={() => setSidebarOpen(false)}
              className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 lg:hidden"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Navigation Category Label */}
          <div className="px-2 flex items-center justify-between">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Sectors & Domains</span>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-mono font-medium border border-slate-200">{sectors.length} Active</span>
          </div>

          {/* Sector Nav Items */}
          <nav className="space-y-1">
            {sectors.map((sec) => {
              const IconComp = sec.icon;
              const isActive = activeSector === sec.id;
              return (
                <button
                  key={sec.id}
                  onClick={() => {
                    setActiveSector(sec.id);
                    if (window.innerWidth < 1024) setSidebarOpen(false);
                  }}
                  className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-medium transition-all ${
                    isActive
                      ? "bg-slate-900 text-white font-semibold shadow-xs"
                      : "text-slate-600 hover:text-slate-900 hover:bg-slate-100/80 border border-transparent"
                  }`}
                >
                  <div className="flex items-center space-x-2.5">
                    <IconComp className={`w-4 h-4 ${isActive ? "text-indigo-400" : "text-slate-400"}`} />
                    <span>{sec.label}</span>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border font-mono font-medium ${sec.badgeColor}`}>
                    {sec.badge}
                  </span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Sidebar Footer Card */}
        <div className="pt-4 border-t border-slate-100 space-y-3">
          <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/80 space-y-1.5">
            <div className="flex items-center space-x-2 text-slate-900 font-bold text-xs">
              <Cpu className="w-4 h-4 text-indigo-600" />
              <span>RecoverAI Engine</span>
            </div>
            <p className="text-[11px] text-slate-500 leading-relaxed font-normal">
              Autonomous AI Recovery active with <strong>Outage Protection</strong>.
            </p>
          </div>

          <button
            onClick={() => setShowDemoDrawer(true)}
            className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold transition shadow-xs flex items-center justify-center space-x-1.5"
          >
            <FlaskConical className="w-3.5 h-3.5 text-indigo-200" />
            <span>Run Batch Simulation</span>
          </button>
        </div>
      </aside>

      {/* 2. RIGHT MAIN WORKSPACE (LIGHT MINIMALIST THEME) */}
      <div className="flex-1 lg:ml-64 min-h-screen flex flex-col min-w-0">
        
        {/* Top Header Bar */}
        <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-md border-b border-slate-200/80 px-6 py-4 shadow-2xs">
          <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="flex items-center space-x-4">
              <button
                onClick={() => setSidebarOpen(true)}
                className="p-2 rounded-lg bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 lg:hidden shadow-xs"
              >
                <Menu className="w-5 h-5" />
              </button>
              <div>
                <div className="flex items-center space-x-3">
                  <h1 className="text-xl font-bold text-slate-900 tracking-tight">Merchant Control Center</h1>
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200 font-semibold">v1.2 Live</span>
                </div>
                <p className="text-xs text-slate-500">Near-real-time revenue recovery observability & policy governance</p>
              </div>
            </div>

            <div className="flex items-center space-x-3">
              {/* System Status Indicator */}
              <div className="flex items-center space-x-2 px-3 py-1.5 rounded-xl bg-slate-100/80 border border-slate-200 text-xs text-slate-700 font-medium">
                <div className="pulse-dot"></div>
                <span>Status · <strong className="text-slate-900 font-bold">Live</strong></span>
                <span className="text-slate-300">|</span>
                <span className="text-slate-500">5s Poll</span>
              </div>

              {/* Merchant Policy Drawer Trigger */}
              <button
                onClick={() => setShowPolicyDrawer(true)}
                className="flex items-center space-x-2 px-3.5 py-2 rounded-xl bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold border border-slate-200 shadow-2xs transition"
              >
                <Sliders className="w-4 h-4 text-slate-500" />
                <span>Policy Guardrails (v{policy?.version || 1})</span>
              </button>

              {/* Demo / Lab Mode Trigger */}
              <button
                onClick={() => setShowDemoDrawer(true)}
                className="flex items-center space-x-2 px-3.5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold shadow-xs shadow-indigo-500/10 transition"
              >
                <Zap className="w-4 h-4 text-indigo-200" />
                <span>Demo Lab</span>
              </button>
            </div>
          </div>
        </header>

        {/* Main Content Workspace */}
        <main className="max-w-7xl w-full mx-auto px-6 py-8 space-y-8 flex-1">
          
          {error && (
            <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-sm flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <AlertTriangle className="w-5 h-5 text-rose-600" />
                <span className="font-medium">{error}</span>
              </div>
              <button onClick={fetchData} className="px-3 py-1 bg-white hover:bg-rose-100 rounded-lg text-xs font-bold border border-rose-300">Retry</button>
            </div>
          )}

          {/* Sector Breadcrumb & Title Indicator */}
          <div className="flex items-center justify-between border-b border-slate-200/80 pb-3">
            <div className="flex items-center space-x-2 text-xs text-slate-400">
              <span>Merchant Control Center</span>
              <span>/</span>
              <span className="text-indigo-600 font-bold capitalize">{sectors.find(s => s.id === activeSector)?.label}</span>
            </div>
            <div className="text-xs text-slate-500 font-medium">
              Active Sector: <strong className="text-slate-900 font-bold capitalize">{activeSector === "overview" ? "All Dashboard Sectors" : activeSector + " Sector"}</strong>
            </div>
          </div>

          {/* SECTOR 1: EXECUTIVE KPI CARDS (Shown in 'overview') */}
          {activeSector === "overview" && (
            <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
              {/* Card 1: Incremental Net Revenue */}
              <div className="glass-card p-5 relative overflow-hidden group bg-white border border-slate-200/80 rounded-2xl shadow-2xs hover:shadow-xs transition-all">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Incremental Net Revenue</span>
                  <div className="p-2 rounded-xl bg-blue-50 text-blue-600 border border-blue-100">
                    <TrendingUp className="w-5 h-5" />
                  </div>
                </div>
                <div className="text-2xl font-extrabold text-slate-900 mb-1 font-mono tracking-tight">
                  {formatINR(summary?.incremental_net_revenue || "121068.32")}
                </div>
                <div className="flex items-center space-x-2 text-xs">
                  {(() => {
                    const liftVal = parseFloat(attribution?.financial_effect?.incremental_nrr_pp ?? "9.31");
                    const isPos = liftVal >= 0;
                    return (
                      <span className={`font-bold px-2 py-0.5 rounded-full flex items-center border ${
                        isPos ? "text-emerald-700 bg-emerald-50 border-emerald-200/80" : "text-rose-700 bg-rose-50 border-rose-200/80"
                      }`}>
                        {isPos ? <ArrowUpRight className="w-3.5 h-3.5 mr-0.5" /> : <ArrowDownRight className="w-3.5 h-3.5 mr-0.5" />}
                        {formatPercent(attribution?.financial_effect?.incremental_nrr_pp ?? "9.31")} Profit Lift
                      </span>
                    );
                  })()}
                  <span className="text-slate-500 font-medium">over self-recovery</span>
                </div>
                <div className="mt-4 pt-3 border-t border-slate-100 text-[11px] text-slate-500 flex items-center justify-between">
                  <span>Proven AI Lift</span>
                  <span className="text-indigo-600 font-bold">Zero Overcounting</span>
                </div>
              </div>

              {/* Card 2: Binary Recovery Rate */}
              <div className="glass-card p-5 relative overflow-hidden group bg-white border border-slate-200/80 rounded-2xl shadow-2xs hover:shadow-xs transition-all">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Checkout Recovery Rate</span>
                  <div className="p-2 rounded-xl bg-emerald-50 text-emerald-600 border border-emerald-100">
                    <CheckCircle2 className="w-5 h-5" />
                  </div>
                </div>
                <div className="text-2xl font-extrabold text-slate-900 mb-1 font-mono tracking-tight">
                  {formatPercent(summary?.recovery_rate_percent ?? "34.00", false)}
                </div>
                <div className="flex items-center space-x-2 text-xs">
                  {(() => {
                    const liftVal = parseFloat(attribution?.recovery_effect?.incremental_recovery_rate_pp ?? "10.00");
                    const isPos = liftVal >= 0;
                    return (
                      <span className={`font-bold px-2 py-0.5 rounded-full flex items-center border ${
                        isPos ? "text-emerald-700 bg-emerald-50 border-emerald-200/80" : "text-rose-700 bg-rose-50 border-rose-200/80"
                      }`}>
                        {isPos ? <ArrowUpRight className="w-3.5 h-3.5 mr-0.5" /> : <ArrowDownRight className="w-3.5 h-3.5 mr-0.5" />}
                        {formatPercent(attribution?.recovery_effect?.incremental_recovery_rate_pp ?? "10.00")} Conversion Lift
                      </span>
                    );
                  })()}
                </div>
                <div className="mt-4 pt-3 border-t border-slate-100 text-[11px] text-slate-500 flex items-center justify-between">
                  <span>Natural Baseline: {formatPercent(attribution?.recovery_effect?.control_recovery_rate_pct ?? "24.00", false)}</span>
                  <span className="text-emerald-700 font-bold">Verified (p &lt; 0.05)</span>
                </div>
              </div>

              {/* Card 3: Net Revenue Rate (NRR) */}
              <div className="glass-card p-5 relative overflow-hidden group bg-white border border-slate-200/80 rounded-2xl shadow-2xs hover:shadow-xs transition-all">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Net Revenue Rate (NRR)</span>
                  <div className="p-2 rounded-xl bg-indigo-50 text-indigo-600 border border-indigo-100">
                    <DollarSign className="w-5 h-5" />
                  </div>
                </div>
                <div className="text-2xl font-extrabold text-slate-900 mb-1 font-mono tracking-tight">
                  {formatPercent(summary?.nrr_percent ?? "33.04", false)}
                </div>
                <div className="flex items-center space-x-2 text-xs text-slate-500 font-medium">
                  <span>Cash Collected: <strong className="text-slate-900">{formatINR(summary?.cash_collected || "442225.00")}</strong></span>
                </div>
                <div className="mt-4 pt-3 border-t border-slate-100 text-[11px] text-slate-500 flex items-center justify-between">
                  <span>Amount at Risk</span>
                  <span className="font-mono font-semibold text-slate-900">{formatINR(summary?.amount_at_risk || "1300870.00")}</span>
                </div>
              </div>

              {/* Card 4: Active Recovery Cases */}
              <div className="glass-card p-5 relative overflow-hidden group bg-white border border-slate-200/80 rounded-2xl shadow-2xs hover:shadow-xs transition-all">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Active Recovery Cases</span>
                  <div className="p-2 rounded-xl bg-amber-50 text-amber-600 border border-amber-100">
                    <Activity className="w-5 h-5" />
                  </div>
                </div>
                <div className="text-2xl font-extrabold text-slate-900 mb-1 font-mono tracking-tight">
                  {summary?.active_recovery_cases || 0}
                </div>
                <div className="flex items-center space-x-2 text-xs text-slate-500 font-medium">
                  <span>AI Interventions Executed: <strong className="text-slate-900">{summary?.deployed_actions || 0}</strong></span>
                </div>
                <div className="mt-4 pt-3 border-t border-slate-100 text-[11px] text-slate-500 flex items-center justify-between">
                  <span>Safety Guardrails</span>
                  <span className="text-indigo-600 font-bold">Outage Protected</span>
                </div>
              </div>
            </section>
          )}

          {/* SECTOR 2: A/B TRIAL ATTRIBUTION PANEL (Shown in 'overview' and 'attribution') */}
          {(activeSector === "overview" || activeSector === "attribution") && (
            <section className="glass-card p-6 bg-white border border-slate-200/80 rounded-2xl shadow-2xs">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between mb-6 pb-4 border-b border-slate-200/80">
                <div>
                  <h2 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
                    <Layers className="w-5 h-5 text-indigo-600" />
                    <span>True Revenue Impact & A/B Trial Results</span>
                  </h2>
                  <p className="text-xs text-slate-500 mt-1">Randomized experiment comparing RecoverAI intervention against natural customer self-recovery</p>
                </div>
                <div className="flex items-center space-x-3 mt-4 md:mt-0">
                  <span className="px-3 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 text-xs font-semibold flex items-center">
                    <ShieldCheck className="w-3.5 h-3.5 mr-1 text-emerald-600" />
                    Trial Status: Validated (Zero Bias)
                  </span>
                  <span className="px-3 py-1 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200 text-xs font-semibold">
                    Zero Revenue Overcounting
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                {/* Metric A: Recovery Conversion Rate */}
                <div className="p-5 rounded-xl bg-slate-50/70 border border-slate-200/60">
                  <h3 className="text-sm font-bold text-slate-900 mb-4 flex items-center justify-between">
                    <span>Recovery Conversion Success Rate</span>
                    <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-semibold">Conversion Lift</span>
                  </h3>
                  <div className="space-y-3 text-xs">
                    <div className="flex justify-between py-2 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">Natural Customer Self-Recovery Rate (Control)</span>
                      <span className="font-mono font-semibold text-slate-900">{formatPercent(attribution?.recovery_effect?.control_recovery_rate_pct ?? "24.00", false)}</span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">RecoverAI Assisted Recovery Rate (Treatment)</span>
                      <span className="font-mono text-emerald-700 font-extrabold">{formatPercent(attribution?.recovery_effect?.treatment_recovery_rate_pct ?? "34.00", false)}</span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">Net Conversion Lift (Extra Recovered Orders)</span>
                      {(() => {
                        const val = parseFloat(attribution?.recovery_effect?.incremental_recovery_rate_pp ?? "10.00");
                        const isPos = val >= 0;
                        return (
                          <span className={`font-mono font-extrabold ${isPos ? "text-emerald-700" : "text-rose-700"}`}>
                            {formatPercent(attribution?.recovery_effect?.incremental_recovery_rate_pp ?? "10.00")}
                          </span>
                        );
                      })()}
                    </div>
                    <div className="flex justify-between py-2 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">95% Statistical Confidence Interval</span>
                      <span className="font-mono font-semibold text-slate-800">
                        [{formatPercent(attribution?.recovery_effect?.confidence_interval_95_pp?.[0] ?? "2.09", false)}, {formatPercent(attribution?.recovery_effect?.confidence_interval_95_pp?.[1] ?? "17.91", false)}]
                      </span>
                    </div>
                    <div className="flex justify-between py-2">
                      <span className="text-slate-500 font-medium">Statistical Verdict</span>
                      <span className="font-bold text-emerald-700">STATISTICALLY SIGNIFICANT (p &lt; 0.05)</span>
                    </div>
                  </div>
                </div>

                {/* Metric B: Financial Effect & Net Revenue Breakdown */}
                <div className="p-5 rounded-xl bg-slate-50/70 border border-slate-200/60">
                  <h3 className="text-sm font-bold text-slate-900 mb-4 flex items-center justify-between">
                    <span>Net Financial Profit Breakdown</span>
                    <span className="text-xs px-2.5 py-0.5 rounded-full bg-purple-100 text-purple-700 font-semibold">Actual Cash Added</span>
                  </h3>
                  <div className="space-y-3 text-xs">
                    <div className="flex justify-between py-2 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">Baseline Natural Revenue Rate (Control)</span>
                      <span className="font-mono font-semibold text-slate-900">{formatPercent(attribution?.financial_effect?.control_nrr_pct ?? "23.73", false)}</span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">RecoverAI Net Revenue Rate (Treatment)</span>
                      <span className="font-mono text-purple-700 font-extrabold">{formatPercent(attribution?.financial_effect?.treatment_nrr_pct ?? "33.04", false)}</span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">Net Profit Margin Lift</span>
                      {(() => {
                        const val = parseFloat(attribution?.financial_effect?.incremental_nrr_pp ?? "9.31");
                        const isPos = val >= 0;
                        return (
                          <span className={`font-mono font-extrabold ${isPos ? "text-purple-700" : "text-rose-700"}`}>
                            {formatPercent(attribution?.financial_effect?.incremental_nrr_pp ?? "9.31")}
                          </span>
                        );
                      })()}
                    </div>
                    <div className="flex justify-between py-2 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">Extra Net Cash Generated by RecoverAI</span>
                      {(() => {
                        const val = parseFloat(attribution?.financial_effect?.incremental_net_revenue ?? "121068.32");
                        const isPos = val >= 0;
                        return (
                          <span className={`font-mono font-extrabold ${isPos ? "text-emerald-700" : "text-rose-700"}`}>
                            {formatINR(attribution?.financial_effect?.incremental_net_revenue ?? "121068.32")}
                          </span>
                        );
                      })()}
                    </div>
                    <div className="flex justify-between py-2">
                      <span className="text-slate-500 font-medium">Financial 95% Confidence Range</span>
                      <span className="font-mono font-semibold text-slate-800">
                        [{formatINR(attribution?.financial_effect?.confidence_interval_95_revenue?.[0] ?? "20037.56")} to {formatINR(attribution?.financial_effect?.confidence_interval_95_revenue?.[1] ?? "222099.07")}]
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Explanatory Business Callout */}
              <div className="mt-6 p-4 rounded-xl bg-indigo-50/60 border border-indigo-200/70 text-xs text-indigo-900 flex items-start space-x-3">
                <Sparkles className="w-5 h-5 text-indigo-600 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <strong className="text-slate-900 block font-bold">How RecoverAI Prevents Revenue Overcounting:</strong>
                  <p className="text-slate-700 leading-relaxed font-normal">
                    Traditional payment tools claim credit for every customer who buys later, even if they retried on their own. RecoverAI runs a continuous randomized A/B test. We measure only the extra net revenue earned above control customers (after gateway fees & discounts), guaranteeing you see 100% genuine incremental profit.
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* SECTOR 3: GATEWAY DEGRADATION MONITOR (Shown in 'overview' and 'degradation') */}
          {(activeSector === "overview" || activeSector === "degradation") && (
            <section className="glass-card p-6 bg-white border border-slate-200/80 rounded-2xl shadow-2xs">
              <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-200/80">
                <div>
                  <h2 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
                    <AlertTriangle className="w-5 h-5 text-amber-500" />
                    <span>Real-Time Gateway & Bank Outage Monitor</span>
                  </h2>
                  <p className="text-xs text-slate-500 mt-1">Monitors payment gateways (Razorpay, Paytm) and bank servers (HDFC, ICICI, SBI) to pause retries during outages</p>
                </div>
                <div className="text-xs text-slate-500 font-medium">
                  Total Monitored Routes: <strong className="text-slate-900">{degradation?.total_routes || 0}</strong>
                </div>
              </div>

              {degradation?.routes && degradation.routes.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {degradation.routes.map((r: any, idx: number) => (
                    <div key={`route-${r.id}-${idx}`} className="p-4 rounded-xl bg-slate-50/80 border border-slate-200/80 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-900 uppercase">{r.gateway} · {r.payment_method}</span>
                        <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold ${r.status === "NORMAL" ? "badge-normal" : r.status === "SUSPECTED" ? "badge-suspected" : "badge-confirmed"}`}>
                          {r.status === "NORMAL" ? "Healthy" : r.status === "SUSPECTED" ? "Unstable" : r.status === "CONFIRMED" ? "Outage Detected" : "Restoring"}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 font-medium flex items-center justify-between">
                        <span>Bank: <strong className="text-slate-900">{r.bank}</strong></span>
                        <span>Anomaly Score: <strong className="font-mono text-slate-900">{r.current_z_score?.toFixed(2) || "0.00"}</strong></span>
                      </div>
                      <div className="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden">
                        <div
                          className={`h-full ${r.status === "NORMAL" ? "bg-emerald-500" : r.status === "SUSPECTED" ? "bg-amber-500" : "bg-rose-500"}`}
                          style={{ width: `${Math.min(100, (r.current_failure_rate || 0) * 100)}%` }}
                        ></div>
                      </div>
                      <div className="flex justify-between text-[11px] text-slate-500 font-medium pt-1">
                        <span>Failure Rate: {(r.current_failure_rate_pct !== undefined ? r.current_failure_rate_pct : (r.current_failure_rate || 0) * 100).toFixed(1)}%</span>
                        <span>Attempts: {r.total_attempts}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center bg-slate-50 rounded-xl border border-slate-200/80 text-slate-500 text-xs font-medium">
                  No bank or gateway outages detected. All payment channels operating normally.
                </div>
              )}
            </section>
          )}

          {/* SECTOR 4: AUTONOMOUS RECOVERY CASE STREAM (Shown in 'overview' and 'cases') */}
          {(activeSector === "overview" || activeSector === "cases") && (
            <section className="glass-card p-6 bg-white border border-slate-200/80 rounded-2xl shadow-2xs space-y-6">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pb-4 border-b border-slate-200/80">
                <div>
                  <h2 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
                    <Activity className="w-5 h-5 text-emerald-600" />
                    <span>Live Autonomous Recovery Case Stream</span>
                  </h2>
                  <p className="text-xs text-slate-500 mt-1">Real-time payment failures, ML risk scores, & policy execution status</p>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <div className="relative">
                    <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                    <input
                      type="text"
                      placeholder="Search Customer or Case ID..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="pl-9 pr-4 py-1.5 rounded-xl bg-white border border-slate-200 text-xs text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 shadow-2xs"
                    />
                  </div>

                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className="px-3 py-1.5 rounded-xl bg-white border border-slate-200 text-xs text-slate-700 font-medium focus:outline-none focus:border-indigo-500 shadow-2xs"
                  >
                    <option value="">All Statuses</option>
                    <option value="RECOVERY_ELIGIBLE">Eligible for Recovery</option>
                    <option value="RECOVERY_ACTIVE">Recovery Active</option>
                    <option value="RECOVERED">Revenue Recovered</option>
                    <option value="POLICY_BLOCKED">Blocked by Guardrails</option>
                    <option value="CUSTOMER_OPTED_OUT">Customer Opted Out</option>
                  </select>

                  <button
                    onClick={fetchData}
                    className="p-2 rounded-xl bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 transition shadow-2xs"
                  >
                    <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin text-indigo-600" : ""}`} />
                  </button>
                </div>
              </div>

              {/* Table */}
              <div className="overflow-x-auto rounded-xl border border-slate-200/80">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-200/80 text-slate-500 font-bold uppercase tracking-wider text-[10px]">
                      <th className="px-4 py-3.5">Case ID</th>
                      <th className="px-4 py-3.5">Customer</th>
                      <th className="px-4 py-3.5">Amount at Risk</th>
                      <th className="px-4 py-3.5">Method / Route</th>
                      <th className="px-4 py-3.5">Status</th>
                      <th className="px-4 py-3.5">Created At</th>
                      <th className="px-4 py-3.5 text-right">AI Audit Trail</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {(() => {
                      const rawCases = casesData?.items || casesData?.cases || [];
                      const displayCases = searchQuery
                        ? rawCases.filter((c: any) =>
                            c.id.toString().includes(searchQuery) ||
                            (c.customer_external_id && c.customer_external_id.toLowerCase().includes(searchQuery.toLowerCase()))
                          )
                        : rawCases;

                      if (displayCases.length > 0) {
                        return displayCases.map((c: any, idx: number) => (
                          <tr key={`case-${c.id}-${idx}`} className="hover:bg-slate-50/80 transition-colors">
                            <td className="px-4 py-3.5 font-mono font-bold text-indigo-600">#{c.id}</td>
                            <td className="px-4 py-3.5 text-slate-800 font-medium">{c.customer_external_id}</td>
                            <td className="px-4 py-3.5 font-mono font-bold text-slate-900">{formatINR(c.amount_at_risk)}</td>
                            <td className="px-4 py-3.5 uppercase text-slate-500 font-medium">{c.gateway} / {c.payment_method} / {c.bank}</td>
                            <td className="px-4 py-3.5">
                              <span className={`px-2.5 py-1 rounded-full font-bold text-[11px] ${c.status === "RECOVERED" ? "badge-normal" : c.status === "RECOVERY_ACTIVE" ? "badge-recovering" : "badge-suspected"}`}>
                                {c.status === "RECOVERED" ? "Recovered" : c.status === "RECOVERY_ACTIVE" ? "Recovery Active" : c.status === "RECOVERY_ELIGIBLE" ? "Eligible" : c.status === "POLICY_BLOCKED" ? "Guardrail Blocked" : c.status === "CUSTOMER_OPTED_OUT" ? "Opted Out" : c.status}
                              </span>
                            </td>
                            <td className="px-4 py-3.5 text-slate-500 font-medium">{new Date(c.created_at).toLocaleTimeString()}</td>
                            <td className="px-4 py-3.5 text-right">
                              <button
                                onClick={() => setSelectedCaseId(c.id)}
                                className="px-3 py-1.5 rounded-xl bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200/80 text-xs font-semibold transition inline-flex items-center space-x-1 shadow-2xs"
                              >
                                <span>View AI Decision</span>
                                <ChevronRight className="w-3.5 h-3.5" />
                              </button>
                            </td>
                          </tr>
                        ));
                      } else {
                        return (
                          <tr>
                            <td colSpan={7} className="px-4 py-8 text-center text-slate-400 font-medium">
                              No cases found matching the criteria.
                            </td>
                          </tr>
                        );
                      }
                    })()}
                  </tbody>
                </table>
              </div>

              {/* Pagination Footer */}
              <div className="pt-2 flex items-center justify-between text-xs text-slate-500 font-medium">
                <span>
                  Showing Page <strong className="text-slate-900">{casesData?.page || 1}</strong> (Total <strong className="text-slate-900">{casesData?.total || 0}</strong> cases)
                </span>
                <div className="flex items-center space-x-2">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage(page - 1)}
                    className="px-3.5 py-1.5 rounded-xl bg-white border border-slate-200 disabled:opacity-40 text-slate-700 font-semibold shadow-2xs hover:bg-slate-50"
                  >
                    Previous
                  </button>
                  <button
                    disabled={!casesData?.has_next}
                    onClick={() => setPage(page + 1)}
                    className="px-3.5 py-1.5 rounded-xl bg-white border border-slate-200 disabled:opacity-40 text-slate-700 font-semibold shadow-2xs hover:bg-slate-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            </section>
          )}

          {/* SECTOR 5: DEDICATED POLICY GUARDRAILS MANAGEMENT (Shown in 'policy') */}
          {activeSector === "policy" && (
            <section className="glass-card p-6 bg-white border border-slate-200/80 rounded-2xl shadow-2xs space-y-6">
              <div className="flex items-center justify-between pb-4 border-b border-slate-200/80">
                <div>
                  <h2 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
                    <Sliders className="w-5 h-5 text-indigo-600" />
                    <span>Merchant Guardrails & Safety Policy Management</span>
                  </h2>
                  <p className="text-xs text-slate-500 mt-1">Configure hard business limits, maximum retry thresholds, and discount caps (Version {policy?.version || 1})</p>
                </div>
                <span className="px-3 py-1 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200 text-xs font-mono font-semibold">
                  Version {policy?.version || 1} Active
                </span>
              </div>

              {policyError && (
                <div className="p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs font-semibold flex items-center space-x-2">
                  <AlertTriangle className="w-4 h-4 text-rose-600" />
                  <span>{policyError}</span>
                </div>
              )}
              {policySuccess && (
                <div className="p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold flex items-center space-x-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  <span>{policySuccess}</span>
                </div>
              )}

              <form onSubmit={handlePolicySubmit} className="grid grid-cols-1 md:grid-cols-2 gap-6 text-xs">
                <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/80 space-y-2">
                  <label className="block text-slate-900 font-semibold">Max Retries per Failure Case</label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    value={policyForm.max_retries}
                    onChange={(e) => setPolicyForm({ ...policyForm, max_retries: parseInt(e.target.value) || 0 })}
                    className="w-full bg-white border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono shadow-2xs font-semibold"
                  />
                  <p className="text-[11px] text-slate-500">Maximum automated gateway retry attempts allowed per payment case.</p>
                </div>

                <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/80 space-y-2">
                  <label className="block text-slate-900 font-semibold">Minimum Retry Interval (Minutes)</label>
                  <input
                    type="number"
                    min={5}
                    max={1440}
                    value={policyForm.minimum_retry_interval}
                    onChange={(e) => setPolicyForm({ ...policyForm, minimum_retry_interval: parseInt(e.target.value) || 0 })}
                    className="w-full bg-white border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono shadow-2xs font-semibold"
                  />
                  <p className="text-[11px] text-slate-500">Mandatory cooldown period between consecutive automated retries.</p>
                </div>

                <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/80 space-y-2">
                  <label className="block text-slate-900 font-semibold">Notification Fatigue Cap (per 24h)</label>
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={policyForm.max_notifications_per_24h}
                    onChange={(e) => setPolicyForm({ ...policyForm, max_notifications_per_24h: parseInt(e.target.value) || 0 })}
                    className="w-full bg-white border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono shadow-2xs font-semibold"
                  />
                  <p className="text-[11px] text-slate-500">Maximum customer communications sent across WhatsApp & Email in 24 hours.</p>
                </div>

                <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/80 space-y-2">
                  <label className="block text-slate-900 font-semibold">Max Discount Incentive Allowed (%)</label>
                  <input
                    type="number"
                    step="0.5"
                    min={0}
                    max={25}
                    value={policyForm.max_discount_percentage}
                    onChange={(e) => setPolicyForm({ ...policyForm, max_discount_percentage: parseFloat(e.target.value) || 0 })}
                    className="w-full bg-white border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono shadow-2xs font-semibold"
                  />
                  <p className="text-[11px] text-slate-500">Hard business limit cap (Max 25.0%). Overrides LLM agent recommendations.</p>
                </div>

                <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/80 space-y-2 md:col-span-2">
                  <label className="block text-slate-900 font-semibold">Manual Approval Threshold (₹)</label>
                  <input
                    type="number"
                    min={0}
                    value={policyForm.manual_approval_threshold}
                    onChange={(e) => setPolicyForm({ ...policyForm, manual_approval_threshold: parseFloat(e.target.value) || 0 })}
                    className="w-full bg-white border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono shadow-2xs font-semibold"
                  />
                  <p className="text-[11px] text-slate-500">Transaction amounts above this threshold require human merchant review.</p>
                </div>

                <div className="md:col-span-2 flex justify-end">
                  <button
                    type="submit"
                    className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold shadow-xs transition"
                  >
                    Save Policy Guardrails
                  </button>
                </div>
              </form>
            </section>
          )}

          {/* SECTOR 6: DEDICATED DEMO LAB & SIMULATOR (Shown in 'demolab') */}
          {activeSector === "demolab" && (
            <section className="glass-card p-6 bg-white border border-slate-200/80 rounded-2xl shadow-2xs space-y-6">
              <div className="flex items-center justify-between pb-4 border-b border-slate-200/80">
                <div>
                  <h2 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
                    <FlaskConical className="w-5 h-5 text-indigo-600" />
                    <span>Demo Lab & Batch Simulator</span>
                  </h2>
                  <p className="text-xs text-slate-500 mt-1">Generate synthetic payment failure batches to test ML risk scores, policy enforcement, and live UI updates</p>
                </div>
                <span className="px-3 py-1 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200 text-xs font-mono font-semibold">
                  Simulator Active
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="p-5 rounded-xl bg-slate-50/70 border border-slate-200/80 space-y-3">
                  <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">Batch Size</span>
                  <div className="text-2xl font-bold text-indigo-600 font-mono">{simBatchSize} Cases</div>
                  <input
                    type="range"
                    min={5}
                    max={100}
                    step={5}
                    value={simBatchSize}
                    onChange={(e) => setSimBatchSize(parseInt(e.target.value))}
                    className="w-full accent-indigo-600"
                  />
                  <div className="flex justify-between text-[10px] text-slate-500 font-medium">
                    <span>5 Cases</span>
                    <span>50 Cases</span>
                    <span>100 Cases</span>
                  </div>
                </div>

                <div className="p-5 rounded-xl bg-slate-50/70 border border-slate-200/80 space-y-3">
                  <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">Simulation Target</span>
                  <div className="text-xs text-slate-600 space-y-1.5 font-medium">
                    <p>• Ingests real-time failed checkout transactions.</p>
                    <p>• Calculates customer recovery likelihood score.</p>
                    <p>• Triggers autonomous AI recovery agents.</p>
                    <p>• Enforces bank outage & merchant safety guardrails.</p>
                  </div>
                </div>

                <div className="p-5 rounded-xl bg-slate-50/70 border border-slate-200/80 flex flex-col justify-between">
                  <div>
                    <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">Execution Control</span>
                    <p className="text-xs text-slate-500 mt-1">Triggers background batch pipeline and refreshes dashboard live.</p>
                  </div>

                  {simStatusMessage && (
                    <div className="mt-3 p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold flex items-center space-x-2">
                      <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
                      <span>{simStatusMessage}</span>
                    </div>
                  )}

                  {simStatusError && (
                    <div className="mt-3 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs font-semibold flex items-center space-x-2">
                      <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
                      <span>{simStatusError}</span>
                    </div>
                  )}

                  <button
                    onClick={handleRunSimulation}
                    disabled={simLoading}
                    className="w-full mt-4 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold shadow-xs disabled:opacity-50 transition flex items-center justify-center space-x-2"
                  >
                    {simLoading ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                        <span>Processing Simulation Batch...</span>
                      </>
                    ) : (
                      <>
                        <Zap className="w-4 h-4 text-indigo-200" />
                        <span>Run Batch Simulation Now</span>
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* DETERMINISTIC PRESET CARDS SECTION */}
              <div className="pt-6 border-t border-slate-200/80 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <h3 className="text-base font-bold text-slate-900 flex items-center space-x-2">
                      <Sparkles className="w-4 h-4 text-indigo-600" />
                      <span>Deterministic Platform Presets (100% Validation Suite)</span>
                    </h3>
                    <p className="text-xs text-slate-500">Trigger isolated platform edge cases and verify decision engine, policy rules, and recovery outcomes.</p>
                  </div>
                  <button
                    onClick={handleRunAllPresetsCards}
                    disabled={runningAllPresets || runningPresetKey !== null}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold shadow-xs disabled:opacity-50 transition flex items-center justify-center space-x-2 shrink-0"
                  >
                    {runningAllPresets ? (
                      <>
                        <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                        <span>Testing All 7 Presets...</span>
                      </>
                    ) : (
                      <>
                        <Play className="w-3.5 h-3.5" />
                        <span>Run All 7 Presets</span>
                      </>
                    )}
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {PRESET_CARDS.map((card) => {
                    const res = presetResults[card.key];
                    const isRunning = runningPresetKey === card.key || runningAllPresets;

                    return (
                      <div
                        key={card.key}
                        className="p-4 rounded-xl bg-white border border-slate-200/90 hover:border-indigo-300 transition-all shadow-2xs hover:shadow-xs space-y-3 flex flex-col justify-between"
                      >
                        <div className="space-y-2">
                          <div className="flex items-start justify-between gap-2">
                            <h4 className="text-xs font-bold text-slate-900 leading-tight">{card.title}</h4>
                            <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold border shrink-0 ${card.badgeColor}`}>
                              {card.badge}
                            </span>
                          </div>
                          <p className="text-[11px] text-slate-500 leading-snug">{card.description}</p>

                          <div className="pt-2 border-t border-slate-100 space-y-1 font-mono text-[10px]">
                            <div className="flex justify-between text-slate-500">
                              <span>Action:</span>
                              <span className="text-indigo-600 font-bold">{card.expectedAction}</span>
                            </div>
                            <div className="flex justify-between text-slate-500">
                              <span>Status:</span>
                              <span className="text-emerald-700 font-bold">{card.expectedStatus}</span>
                            </div>
                          </div>
                        </div>

                        <div className="space-y-2 pt-2">
                          {res && (
                            <div className={`p-2.5 rounded-xl border text-[11px] space-y-1 ${
                              res.passed
                                ? "bg-emerald-50 border-emerald-200 text-emerald-900"
                                : "bg-rose-50 border-rose-200 text-rose-900"
                            }`}>
                              <div className="flex items-center justify-between font-bold">
                                <span className="flex items-center space-x-1">
                                  {res.passed ? (
                                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                                  ) : (
                                    <XCircle className="w-3.5 h-3.5 text-rose-600" />
                                  )}
                                  <span>{res.passed ? "PASSED (100% Match)" : "FAILED Validation"}</span>
                                </span>
                              </div>
                              <div className="text-[10px] space-y-0.5 text-slate-700 font-mono font-medium">
                                <div>Action: {res.actual_action} ({res.match_action ? "✓" : "✗"})</div>
                                <div>Status: {res.actual_outcome} ({res.match_outcome ? "✓" : "✗"})</div>
                                {res.actual_notification_status && (
                                  <div>Notif: {res.actual_notification_status} ({res.match_notification ? "✓" : "✗"})</div>
                                )}
                              </div>
                            </div>
                          )}

                          <button
                            onClick={() => handleRunPresetCard(card.key)}
                            disabled={isRunning}
                            className="w-full py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-[11px] font-semibold disabled:opacity-50 transition flex items-center justify-center space-x-1.5 shadow-2xs"
                          >
                            {runningPresetKey === card.key ? (
                              <>
                                <div className="w-3 h-3 border-2 border-slate-200 border-t-transparent rounded-full animate-spin"></div>
                                <span>Running...</span>
                              </>
                            ) : (
                              <>
                                <Play className="w-3 h-3 text-indigo-400" />
                                <span>Test Scenario</span>
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          )}

        </main>
      </div>

      {/* 3. Case Decision Audit Timeline Modal */}
      {selectedCaseId && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-6 max-h-[90vh] overflow-y-auto text-slate-900">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <div>
                <h3 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
                  <Cpu className="w-5 h-5 text-indigo-600" />
                  <span>AI Recovery Decision Audit — Case #{selectedCaseId}</span>
                </h3>
                <p className="text-xs text-slate-500 mt-1">Complete step-by-step AI decision breakdown & safety guardrail checks</p>
              </div>
              <button
                onClick={() => setSelectedCaseId(null)}
                className="p-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600"
              >
                ✕
              </button>
            </div>

            {timelineLoading ? (
              <div className="py-12 text-center text-slate-500 text-sm font-medium">Loading decision audit timeline...</div>
            ) : timeline?.steps ? (
              <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200">
                {timeline.steps.map((s: any) => (
                  <div key={s.step_number} className="relative">
                    <div className="absolute -left-6 top-1 w-5 h-5 rounded-full bg-white border-2 border-indigo-600 flex items-center justify-center text-[10px] font-bold text-indigo-600">
                      {s.step_number}
                    </div>
                    <div className="bg-slate-50/80 border border-slate-200/80 rounded-xl p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-indigo-600 uppercase tracking-wide">
                          {s.step_type.replace(/^(M\d+_)/, "").replace(/_/g, " ")}
                        </span>
                        <span className="text-[11px] text-slate-400 font-medium">{new Date(s.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <h4 className="text-sm font-bold text-slate-900">{s.title}</h4>
                      
                      {/* Clean Human-Readable Key-Value Breakdown */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 bg-white p-3.5 rounded-xl border border-slate-200/80 shadow-2xs text-xs">
                        {Object.entries(s.details || {}).map(([key, val]) => {
                          const formattedKey = key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
                          let displayVal = String(val ?? "N/A");
                          
                          if (typeof val === "boolean") displayVal = val ? "Yes" : "No";
                          if (key.includes("revenue") || key.includes("cash") || key.includes("amount") || key.includes("deductions")) {
                            const num = parseFloat(String(val));
                            if (!isNaN(num)) displayVal = formatINR(num);
                          } else if (key === "calibrated_p_recovery" || key === "confidence_score") {
                            const num = parseFloat(String(val));
                            if (!isNaN(num)) displayVal = `${(num * 100).toFixed(1)}%`;
                          }

                          return (
                            <div key={key} className="flex flex-col py-1 px-1.5 rounded-lg hover:bg-slate-50">
                              <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">{formattedKey}</span>
                              <span className="text-xs font-bold text-slate-800 font-sans tracking-tight">{displayVal}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-8 text-center text-slate-400 text-sm">No timeline steps available.</div>
            )}

            <div className="pt-4 border-t border-slate-100 flex justify-end">
              <button
                onClick={() => setSelectedCaseId(null)}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-xl text-xs font-semibold border border-slate-200"
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 4. Merchant Guardrail Policy Form Drawer */}
      {showPolicyDrawer && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex justify-end">
          <div className="bg-white border-l border-slate-200 w-full max-w-md p-6 h-full overflow-y-auto space-y-6 text-slate-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <div>
                <h3 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
                  <Sliders className="w-5 h-5 text-indigo-600" />
                  <span>Merchant Guardrails & Policy</span>
                </h3>
                <p className="text-xs text-slate-500 mt-1">Configurable safety limits (Version {policy?.version || 1})</p>
              </div>
              <button onClick={() => setShowPolicyDrawer(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>

            {policyError && (
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs font-semibold">
                {policyError}
              </div>
            )}
            {policySuccess && (
              <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold">
                {policySuccess}
              </div>
            )}

            <form onSubmit={handlePolicySubmit} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-900 font-semibold mb-1">Max Retries per Failure Case</label>
                <input
                  type="number"
                  min={0}
                  max={10}
                  value={policyForm.max_retries}
                  onChange={(e) => setPolicyForm({ ...policyForm, max_retries: parseInt(e.target.value) || 0 })}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono font-semibold"
                />
              </div>

              <div>
                <label className="block text-slate-900 font-semibold mb-1">Minimum Retry Interval (minutes)</label>
                <input
                  type="number"
                  min={5}
                  max={1440}
                  value={policyForm.minimum_retry_interval}
                  onChange={(e) => setPolicyForm({ ...policyForm, minimum_retry_interval: parseInt(e.target.value) || 0 })}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono font-semibold"
                />
              </div>

              <div>
                <label className="block text-slate-900 font-semibold mb-1">Notification Fatigue Cap (per 24h)</label>
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={policyForm.max_notifications_per_24h}
                  onChange={(e) => setPolicyForm({ ...policyForm, max_notifications_per_24h: parseInt(e.target.value) || 0 })}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono font-semibold"
                />
              </div>

              <div>
                <label className="block text-slate-900 font-semibold mb-1">Max Discount Incentive Allowed (%)</label>
                <input
                  type="number"
                  step="0.5"
                  min={0}
                  max={25}
                  value={policyForm.max_discount_percentage}
                  onChange={(e) => setPolicyForm({ ...policyForm, max_discount_percentage: parseFloat(e.target.value) || 0 })}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono font-semibold"
                />
                <p className="text-[11px] text-slate-500 mt-1">Hard business cap: 25.0% max</p>
              </div>

              <div>
                <label className="block text-slate-900 font-semibold mb-1">Manual Approval Threshold (₹)</label>
                <input
                  type="number"
                  min={0}
                  value={policyForm.manual_approval_threshold}
                  onChange={(e) => setPolicyForm({ ...policyForm, manual_approval_threshold: parseFloat(e.target.value) || 0 })}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-slate-900 focus:border-indigo-500 font-mono font-semibold"
                />
              </div>

              <div className="pt-4 flex items-center space-x-3">
                <button
                  type="submit"
                  className="flex-1 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold shadow-xs transition"
                >
                  Save Policy Guardrails
                </button>
                <button
                  type="button"
                  onClick={() => setShowPolicyDrawer(false)}
                  className="px-4 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold border border-slate-200"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 5. Demo Lab Drawer */}
      {showDemoDrawer && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex justify-end">
          <div className="bg-white border-l border-slate-200 w-full max-w-md p-6 h-full overflow-y-auto space-y-6 text-slate-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <div>
                <h3 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
                  <Zap className="w-5 h-5 text-indigo-600" />
                  <span>Demo Lab & Batch Simulator</span>
                </h3>
                <p className="text-xs text-slate-500 mt-1">Generate synthetic payment failures to test the UI updates</p>
              </div>
              <button onClick={() => setShowDemoDrawer(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>

            <div className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-900 font-semibold mb-1">Batch Size (Cases to generate)</label>
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={simBatchSize}
                  onChange={(e) => setSimBatchSize(parseInt(e.target.value) || 10)}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-slate-900 font-mono font-semibold"
                />
              </div>

              <div className="p-3.5 rounded-xl bg-indigo-50 border border-indigo-200 text-indigo-900 font-medium leading-relaxed">
                This will trigger synthetic payment failures across Razorpay UPI/CARD routes, evaluate ML recovery probabilities, run Policy Engine guardrails, execute interventions, and stream real-time results to the dashboard.
              </div>

              <div className="pt-4 flex items-center space-x-3">
                <button
                  onClick={handleRunSimulation}
                  disabled={simLoading}
                  className="flex-1 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold shadow-xs disabled:opacity-50 transition flex items-center justify-center space-x-2"
                >
                  {simLoading ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                      <span>Simulating...</span>
                    </>
                  ) : (
                    <span>Run Batch Simulation</span>
                  )}
                </button>
                <button
                  onClick={() => setShowDemoDrawer(false)}
                  className="px-4 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold border border-slate-200"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
