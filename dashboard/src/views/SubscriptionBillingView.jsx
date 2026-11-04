import React, { useState, useEffect } from "react";
import {
  CreditCard,
  CheckCircle2,
  Zap,
  ShieldCheck,
  TrendingUp,
  AlertTriangle,
  AlertCircle,
  QrCode,
  Building,
  Smartphone,
  Check,
  Loader2,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export function SubscriptionBillingView() {
  const { tenantId, userEmail } = useAuth();
  const [currency, setCurrency] = useState("INR"); // 'INR' or 'USD'
  const [activePlanId, setActivePlanId] = useState("business");
  const [loading, setLoading] = useState(false);
  const [paymentModal, setPaymentModal] = useState(null); // plan object if open
  const [paymentMethod, setPaymentMethod] = useState("upi"); // 'upi', 'netbanking', 'card'
  const [isProcessingPayment, setIsProcessingPayment] = useState(false);
  const [paymentSuccess, setPaymentSuccess] = useState(null);
  const [paymentError, setPaymentError] = useState(null);

  const defaultPlans = [
    {
      id: "developer",
      name: "Developer Sandbox",
      priceINR: "₹0",
      priceUSD: "$0",
      period: "forever",
      description: "Ideal for prototyping, evaluation, and local development test suites.",
      features: [
        "10,000 Assured transactions / mo",
        "2 Concurrent Lease Fencers",
        "Full 5-Gate Pipeline Verification",
        "Community Support & Docs",
      ],
      popular: false,
    },
    {
      id: "business",
      name: "Pro / Starter",
      priceINR: "₹1,999",
      priceUSD: "$29",
      period: "per month",
      description: "Accessible production assurance for indie developers and growth AI agent teams.",
      features: [
        "75,000 Assured transactions / mo",
        "10 Concurrent Lease Fencers",
        "Managed Qdrant Vector Memory",
        "OpenAI Drop-In Gateway Proxy",
        "LangGraph Self-Healing Auto-Correction",
        "Cryptographic SHA-256 Audit Ledger",
      ],
      popular: true,
    },
    {
      id: "enterprise",
      name: "Enterprise Sentinel",
      priceINR: "₹24,999",
      priceUSD: "$299",
      period: "per month",
      description: "Dedicated isolation, custom SLAs, and high-frequency real-world mediation.",
      features: [
        "2,000,000+ Assured transactions / mo",
        "Unlimited Distributed Lease Fencers",
        "Dedicated PostgreSQL RLS schema isolation",
        "Custom Reality Verification Adapters",
        "99.95% Execution SLA guarantee",
        "24/7 Designated Escalation Engineer",
      ],
      popular: false,
    },
  ];

  const [plans, setPlans] = useState(defaultPlans);

  useEffect(() => {
    async function loadDynamicPlans() {
      try {
        const backendPlans = await api.getBillingPlans();
        if (Array.isArray(backendPlans) && backendPlans.length > 0) {
          const mapped = backendPlans.map((bp) => ({
            id: bp.tier?.toLowerCase() || bp.id,
            name: bp.name,
            priceINR: `₹${Number(bp.price_inr_monthly || 0).toLocaleString("en-IN")}`,
            priceUSD: `$${bp.price_dollars_monthly || 0}`,
            period: bp.tier?.toLowerCase() === "developer" ? "forever" : "per month",
            description: bp.tagline || "",
            features: (bp.features || []).map((f) => (typeof f === "object" ? f.title : f)),
            popular: bp.tier?.toLowerCase() === "business",
          }));
          setPlans(mapped);
        }
      } catch {
        // Retain default calibrated plans
      }
    }
    loadDynamicPlans();
  }, []);

  const handleOpenCheckout = (plan) => {
    if (plan.id === "developer") {
      setActivePlanId("developer");
      setPaymentSuccess("Subscribed to Developer Sandbox (Free Forever).");
      return;
    }
    setPaymentModal(plan);
  };

  const handleSimulatePayment = async () => {
    if (!paymentModal) return;
    setIsProcessingPayment(true);
    setPaymentError(null);
    setPaymentSuccess(null);

    try {
      // 1. Create Razorpay order via gateway
      const order = await api.createRazorpayOrder(paymentModal.id);
      if (!order || !order.order_id) {
        throw new Error(order?.detail || "Could not initialize payment order with gateway.");
      }

      // 2. Load official Razorpay checkout script
      const scriptLoaded = await new Promise((resolve) => {
        if (window.Razorpay) return resolve(true);
        const script = document.createElement("script");
        script.src = "https://checkout.razorpay.com/v1/checkout.js";
        script.onload = () => resolve(true);
        script.onerror = () => resolve(false);
        document.body.appendChild(script);
      });

      if (!scriptLoaded || !window.Razorpay) {
        throw new Error("Unable to load Razorpay checkout SDK. Please verify internet connectivity.");
      }

      // 3. Launch Razorpay payment sheet
      const options = {
        key: order.key_id,
        amount: order.amount_paise,
        currency: order.currency || "INR",
        name: "MIRAGE AI Execution Assurance",
        description: `${paymentModal.name} Subscription`,
        order_id: order.order_id,
        handler: async (response) => {
          try {
            await api.verifyRazorpayPayment(
              response.razorpay_order_id || order.order_id,
              response.razorpay_payment_id,
              response.razorpay_signature,
              paymentModal.id
            );
            setActivePlanId(paymentModal.id);
            setPaymentSuccess(
              `Payment successful! ${paymentModal.name} active for workspace ${tenantId}. Official tax invoice dispatched to your email.`
            );
            setPaymentModal(null);
          } catch (err) {
            setPaymentError(err.message || "Cryptographic payment verification failed on server.");
          } finally {
            setIsProcessingPayment(false);
          }
        },
        modal: {
          ondismiss: () => {
            setIsProcessingPayment(false);
          },
        },
        prefill: {
          email: userEmail || "",
        },
        theme: {
          color: "#0284c7",
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.on("payment.failed", (response) => {
        setPaymentError(`Payment failed: ${response.error?.description || "Transaction declined by issuing authority."}`);
        setIsProcessingPayment(false);
      });
      rzp.open();
    } catch (err) {
      setPaymentError(err.message || "Payment initiation failed. Please check your credentials or network.");
      setIsProcessingPayment(false);
    }
  };

  return (
    <div className="space-y-8 pb-12">
      {/* Title & Currency Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-mirage-text">
            Subscriptions & Budget Headroom
          </h1>
          <p className="text-mirage-subtext text-sm mt-1">
            Commercial SaaS plans with instant online checkout via Razorpay (UPI, Netbanking, Cards).
          </p>
        </div>

        {/* Currency Toggle */}
        <div className="flex items-center space-x-1 p-1 bg-mirage-surface rounded border border-mirage-border shadow-sm self-start sm:self-auto">
          <button
            type="button"
            onClick={() => setCurrency("INR")}
            className={`px-3 py-1.5 rounded text-xs font-semibold transition ${
              currency === "INR"
                ? "bg-mirage-cyan text-white shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
            }`}
          >
            ₹ INR (India)
          </button>
          <button
            type="button"
            onClick={() => setCurrency("USD")}
            className={`px-3 py-1.5 rounded text-xs font-semibold transition ${
              currency === "USD"
                ? "bg-mirage-cyan text-white shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
            }`}
          >
            $ USD (Global)
          </button>
        </div>
      </div>

      {paymentSuccess && (
        <div className="p-4 rounded bg-mirage-emerald/10 border border-mirage-emerald/20 text-xs sm:text-sm text-mirage-emerald flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-5 h-5 shrink-0" />
            <span>{paymentSuccess}</span>
          </div>
          <button
            type="button"
            onClick={() => setPaymentSuccess(null)}
            className="text-xs text-mirage-subtext hover:text-mirage-text"
          >
            Dismiss
          </button>
        </div>
      )}

      {paymentError && (
        <div className="p-4 rounded bg-mirage-crimson/10 border border-mirage-crimson/20 text-xs sm:text-sm text-mirage-crimson flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <AlertCircle className="w-5 h-5 shrink-0" />
            <span>{paymentError}</span>
          </div>
          <button
            type="button"
            onClick={() => setPaymentError(null)}
            className="text-xs text-mirage-subtext hover:text-mirage-text"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Spend Ceiling & Quota Gauge */}
      <div className="bg-mirage-surface rounded p-6 border border-mirage-border shadow-mirage-surface space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-4 border-b border-mirage-border">
          <div>
            <div className="text-xs text-mirage-subtext uppercase tracking-wider font-semibold">
              Current Plan & Headroom
            </div>
            <div className="text-lg font-bold text-mirage-text mt-0.5">
              {plans.find((p) => p.id === activePlanId)?.name}
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-mirage-emerald animate-pulse" />
            <span className="text-xs font-mono font-medium text-mirage-text">
              Budget Status: HEALTHY
            </span>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex justify-between text-xs text-mirage-subtext">
            <span>Monthly Consumption: 18,420 / 250,000 transactions</span>
            <span className="font-semibold text-mirage-text">7.3% used</span>
          </div>
          <div className="w-full h-2 rounded-full bg-mirage-surfaceElevated border border-mirage-border overflow-hidden">
            <div className="h-full bg-mirage-cyan rounded-full" style={{ width: "7.3%" }} />
          </div>
        </div>
      </div>

      {/* Pricing Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {plans.map((p) => {
          const isCurrent = activePlanId === p.id;
          const displayPrice = currency === "INR" ? p.priceINR : p.priceUSD;

          return (
            <div
              key={p.id}
              className={`rounded p-6 flex flex-col justify-between transition-all ${
                p.popular
                  ? "bg-mirage-surface border-2 border-mirage-cyan shadow-hud-panel relative"
                  : "bg-mirage-surface border border-mirage-border shadow-mirage-surface hover:shadow-hud-panel"
              }`}
            >
              {p.popular && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-mirage-cyan text-white text-[10px] font-bold uppercase tracking-wider shadow-sm">
                  Most Popular
                </div>
              )}

              <div>
                <h3 className="text-lg font-bold text-mirage-text">{p.name}</h3>
                <p className="text-xs text-mirage-subtext mt-1 min-h-[32px]">{p.description}</p>

                <div className="my-6">
                  <span className="text-3xl sm:text-4xl font-extrabold text-mirage-text tracking-tight">
                    {displayPrice}
                  </span>
                  <span className="text-xs text-mirage-subtext ml-1.5">/ {p.period}</span>
                </div>

                <div className="space-y-2.5 border-t border-mirage-border pt-4">
                  {p.features.map((feat, i) => (
                    <div key={i} className="flex items-start space-x-2.5 text-xs text-mirage-text">
                      <Check className="w-4 h-4 text-mirage-emerald shrink-0 mt-0.5" />
                      <span>{feat}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="pt-6 mt-6 border-t border-mirage-border">
                <button
                  type="button"
                  disabled={isCurrent}
                  onClick={() => handleOpenCheckout(p)}
                  className={`w-full py-2.5 rounded text-xs font-semibold transition shadow-sm ${
                    isCurrent
                      ? "bg-mirage-surfaceElevated text-mirage-muted border border-mirage-border cursor-default"
                      : p.popular
                      ? "bg-mirage-cyan hover:bg-mirage-cyanHover text-white"
                      : "bg-mirage-text hover:bg-black text-white"
                  }`}
                >
                  {isCurrent ? "Current Plan" : `Upgrade to ${p.name}`}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Payment Modal (Razorpay / Stripe) */}
      {paymentModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-mirage-surface rounded max-w-md w-full p-6 border border-mirage-border shadow-hud-panel space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-mirage-border">
              <div>
                <h3 className="text-base font-bold text-mirage-text">
                  Complete Subscription Checkout
                </h3>
                <p className="text-xs text-mirage-subtext mt-0.5">
                  Plan: <span className="font-semibold text-mirage-text">{paymentModal.name}</span>
                </p>
              </div>
              <div className="text-right">
                <div className="text-lg font-bold text-mirage-cyan font-mono">
                  {currency === "INR" ? paymentModal.priceINR : paymentModal.priceUSD}
                </div>
                <div className="text-[10px] text-mirage-muted">per month</div>
              </div>
            </div>

            {/* Payment Method Selector */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-mirage-text block">
                Select Razorpay Payment Method
              </label>
              <div className="grid grid-cols-3 gap-2">
                <button
                  type="button"
                  onClick={() => setPaymentMethod("upi")}
                  className={`p-3 rounded border text-center transition ${
                    paymentMethod === "upi"
                      ? "bg-mirage-cyan/10 border-mirage-cyan text-mirage-cyan font-semibold"
                      : "bg-mirage-surfaceElevated border-mirage-border text-mirage-subtext hover:text-mirage-text"
                  }`}
                >
                  <Smartphone className="w-4 h-4 mx-auto mb-1" />
                  <span className="text-[11px] block">UPI / QR</span>
                </button>

                <button
                  type="button"
                  onClick={() => setPaymentMethod("card")}
                  className={`p-3 rounded border text-center transition ${
                    paymentMethod === "card"
                      ? "bg-mirage-cyan/10 border-mirage-cyan text-mirage-cyan font-semibold"
                      : "bg-mirage-surfaceElevated border-mirage-border text-mirage-subtext hover:text-mirage-text"
                  }`}
                >
                  <CreditCard className="w-4 h-4 mx-auto mb-1" />
                  <span className="text-[11px] block">Cards</span>
                </button>

                <button
                  type="button"
                  onClick={() => setPaymentMethod("netbanking")}
                  className={`p-3 rounded border text-center transition ${
                    paymentMethod === "netbanking"
                      ? "bg-mirage-cyan/10 border-mirage-cyan text-mirage-cyan font-semibold"
                      : "bg-mirage-surfaceElevated border-mirage-border text-mirage-subtext hover:text-mirage-text"
                  }`}
                >
                  <Building className="w-4 h-4 mx-auto mb-1" />
                  <span className="text-[11px] block">Netbanking</span>
                </button>
              </div>
            </div>

            {/* Simulated Payment Method Preview */}
            <div className="p-4 rounded bg-mirage-surfaceElevated border border-mirage-border text-xs text-mirage-subtext space-y-2">
              {paymentMethod === "upi" && (
                <div>
                  <div className="font-semibold text-mirage-text mb-1">Instant UPI &amp; Dynamic QR</div>
                  <div className="text-[11px]">Pay via Google Pay, PhonePe, Paytm, or BHIM UPI ID</div>
                </div>
              )}
              {paymentMethod === "card" && (
                <div>
                  <div className="font-semibold text-mirage-text mb-1">RuPay, Visa, Mastercard</div>
                  <div className="text-[11px]">Indian &amp; International cards with RBI-mandated 2FA OTP verification</div>
                </div>
              )}
              {paymentMethod === "netbanking" && (
                <div>
                  <div className="font-semibold text-mirage-text mb-1">50+ Indian Banks</div>
                  <div className="text-[11px]">HDFC, ICICI, SBI, Axis, Kotak, and all major retail netbanking</div>
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className="grid grid-cols-2 gap-3 pt-2">
              <button
                type="button"
                onClick={() => setPaymentModal(null)}
                className="py-2.5 rounded border border-mirage-border bg-mirage-surfaceElevated text-xs font-semibold text-mirage-text hover:bg-mirage-border/50 transition"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isProcessingPayment}
                onClick={handleSimulatePayment}
                className="py-2.5 rounded bg-mirage-cyan hover:bg-mirage-cyanHover text-white text-xs font-semibold shadow-sm transition flex items-center justify-center space-x-2 disabled:opacity-50"
              >
                {isProcessingPayment ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Processing with Razorpay...</span>
                  </>
                ) : (
                  <span>Pay with Razorpay</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
