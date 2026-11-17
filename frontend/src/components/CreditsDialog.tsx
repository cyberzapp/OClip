"use client";

import { useEffect, useRef, useState } from "react";
import { Coins, Plus, X } from "lucide-react";
import { CreditWallet } from "@/lib/types";

interface Props {
  open: boolean;
  wallet: CreditWallet | null;
  onClose: () => void;
  onUpdated: (w: CreditWallet) => void;
}

export default function CreditsDialog({ open, wallet, onClose, onUpdated }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  }, [open]);

  const handleClose = () => {
    const el = dialogRef.current;
    if (el) el.returnValue = "";
    onClose();
  };

  const handleTopup = async (amount: number) => {
    setLoading(true);
    try {
      const res = await fetch("/api/credits/topup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount }),
      });
      if (res.ok) {
        onUpdated(await res.json());
      }
    } finally {
      setLoading(false);
    }
  };

  const rates = wallet?.recipeRates ? Object.entries(wallet.recipeRates) : [];

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="credits-title"
      onClose={handleClose}
      className="w-full max-w-2xl rounded-2xl border border-white/10 bg-[#121521] p-6 text-gray-100 shadow-2xl"
    >
      <div className="mb-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/20 text-amber-400">
            <Coins className="h-5 w-5" />
          </div>
          <div>
            <h2 id="credits-title" className="text-base font-semibold">
              OClip Credits & Usage Ledger
            </h2>
            <p className="text-xs text-gray-400">
              Track local AI credit consumption across all 8 Recipes and Studio tools.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleClose}
          aria-label="Close credits dialog"
          className="rounded-lg p-1.5 text-gray-400 hover:bg-white/10 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Balance Banner */}
      <div className="mb-5 flex items-center justify-between rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
        <div>
          <div className="text-xs text-amber-200/80">Current Balance</div>
          <div className="text-2xl font-bold text-amber-300">
            {(wallet?.balance ?? 0).toLocaleString()} credits
          </div>
        </div>
        <button
          type="button"
          onClick={() => handleTopup(1000)}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-xl bg-amber-500 px-3.5 py-2 text-xs font-semibold text-black hover:bg-amber-400 disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" /> +1,000 Local Credits
        </button>
      </div>

      {/* 8 Recipe Rates */}
      <div className="mb-5">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
          Preset Recipe Credit Rates (per minute of processed video)
        </h3>
        <div className="grid grid-cols-2 gap-2 text-xs">
          {rates.map(([id, r]) => (
            <div key={id} className="flex items-center justify-between rounded-lg border border-white/10 bg-[#0b0d14] px-3 py-2">
              <span className="font-medium text-gray-200">{r.label}</span>
              <span className="font-semibold text-amber-300">{r.basePerMin} cr/min</span>
            </div>
          ))}
        </div>
      </div>

      {/* Transaction History */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
          Recent Credit History
        </h3>
        <div className="max-h-56 space-y-1.5 overflow-y-auto pr-1">
          {(wallet?.transactions || []).length === 0 ? (
            <p className="text-xs text-gray-500">No transactions yet.</p>
          ) : (
            (wallet?.transactions || []).map((t) => (
              <div key={t.id} className="flex items-center justify-between rounded-lg border border-white/5 bg-[#0b0d14] px-3 py-2 text-xs">
                <div className="min-w-0 pr-3">
                  <div className="truncate font-medium text-gray-200">{t.description}</div>
                  <div className="text-[10px] text-gray-500">{t.action} • Balance: {t.balance_after}</div>
                </div>
                <span className={`shrink-0 font-mono font-semibold ${t.amount >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  {t.amount >= 0 ? `+${t.amount}` : t.amount}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </dialog>
  );
}
