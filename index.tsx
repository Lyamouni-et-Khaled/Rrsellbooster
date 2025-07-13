/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { createRoot } from 'react-dom/client';

const JsonCard = ({ title, data }) => (
    <details className="card" open={false}>
        <summary className="card-header card-title">{title}</summary>
        <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
);

const getProductPriceDisplay = (p) => {
    const currency = p.currency || 'EUR';
    if (p.price_text) {
        return p.price_text;
    }
    if (p.options && p.options.length > 0) {
        try {
            const prices = p.options.map(opt => opt.price);
            const minPrice = Math.min(...prices);
            return `À partir de ${minPrice.toFixed(2)} ${currency}`;
        } catch (e) {
            return "Prix variable";
        }
    }
    if (p.price != null && p.price >= 0) {
        return `${p.price.toFixed(2)} ${currency}`;
    }
    return 'Prix sur demande';
};

const getCategoryIcon = (category) => {
    const iconStyle = { marginRight: '0.75rem', flexShrink: 0, color: 'var(--primary)', transition: 'color 0.3s ease' };
    switch (category) {
        case 'Services & Avantages Discord':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9.09 9.09.41-3.1L12 7.5l2.5-1.51.41 3.1-2.1 2.1 3.1.41L14.5 12l1.51 2.5-3.1.41-2.1-2.1-.41 3.1L9.5 12l-1.51-2.5z"/></svg>;
        case 'Ebooks & Guides':
        case 'Formations':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg>;
        case 'Comptes Premium':
        case 'Services Financiers':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 21v-3.5a2.5 2.5 0 0 1 5 0V21"/><path d="M7 21v-3.5a2.5 2.5 0 0 0-5 0V21"/><rect width="20" height="10" x="2" y="3" rx="2"/><circle cx="8" cy="8" r="1"/><circle cx="16" cy="8" r="1"/><path d="M12 8h.01"/></svg>;
        case 'Gaming - Outils':
        case 'Gaming - Monnaie Virtuelle':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2.5 6.5A2.5 2.5 0 0 1 5 4h14a2 2 0 0 1 2 2v7.5a2.5 2.5 0 0 1-2.5 2.5H5A2.5 2.5 0 0 1 2.5 14Z"/><path d="M6 18h12"/><path d="M10 12h4v-2h-4v2z"/><path d="M10 6.5v-2.5"/><path d="M14 6.5v-2.5"/></svg>;
        case 'Panels':
        case 'Outils & Logiciels':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 14v-2a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v2"/></svg>;
        case 'Services de Création':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 5-3-3-3 3"/><path d="m15 19 3 3 3-3"/><path d="M4 9v6"/><path d="M9 4h6"/><path d="M20 9v6"/><path d="M9 20h6"/></svg>;
        case 'Logs':
             return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>;
        case 'Boost Réseaux Sociaux':
             return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>;
        case 'Fournisseurs & Accès Exclusifs':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13.4 2H6.6l-2 9h15.2z"/><path d="M22 13v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6h20z"/><path d="M12 17a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"/></svg>;
        default:
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>;
    }
}

const getCreditShopIcon = (iconName) => {
    const iconStyle = { marginRight: '0.75rem', flexShrink: 0, color: 'var(--primary)', transition: 'color 0.3s ease' };
    switch (iconName) {
        case 'rocket':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.3.05-3.18-.65-.87-2.12-1.51-3.18-1.82zM12 12l9.5-9.5M12 12l6.5-6.5M12 12l.5 3.5 3.5.5M7.5 12l-6.5 6.5"/></svg>;
        case 'trending_up':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>;
        case 'level_up':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5h.01"/><path d="M16 8h.01"/><path d="M8 8h.01"/><path d="M12 12h.01"/><path d="m16 12-.5-2.5-2.5-.5"/><path d="M8 12l.5-2.5 2.5-.5"/><path d="M12 19.5.5 12 12 .5l11.5 11.5Z"/></svg>;
        case 'ticket':
            return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9a3 3 0 0 1 0 6v3a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-3a3 3 0 0 1 0-6V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2"/><path d="M13 17v2"/><path d="M13 11v2"/></svg>;
        default:
             return <svg aria-hidden="true" style={iconStyle} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21v-3.5a2.5 2.5 0 0 1 5 0V21"/><path d="M7 21v-3.5a2.5 2.5 0 0 0-5 0V21"/><rect width="20" height="10" x="2" y="3" rx="2"/><circle cx="8" cy="8" r="1"/><circle cx="16" cy="8" r="1"/><path d="M12 8h.01"/></svg>;
    }
};

const ProductsCard = ({ title, products }) => (
    <div className="card">
        <div className="card-header">
            <h2 className="card-title">{title}</h2>
        </div>
        <div className="grid">
            {products.map(p => (
                <div key={p.id} className="product-card">
                    <span className="category">{p.category}</span>
                    <div style={{ display: 'flex', alignItems: 'center', margin: '0.5rem 0' }}>
                        {getCategoryIcon(p.category)}
                        <h3 style={{ margin: 0 }}>{p.name}</h3>
                    </div>
                    <p style={{ color: 'var(--text-secondary)', flexGrow: 1, margin: '0.5rem 0' }}>{p.description}</p>
                    <div className="price">{getProductPriceDisplay(p)}</div>
                    <small style={{color: 'var(--text-secondary)'}}>ID: {p.id}</small>
                </div>
            ))}
        </div>
    </div>
);

const CreditShopCard = ({ title, items }) => (
    <div className="card">
        <div className="card-header">
            <h2 className="card-title">{title}</h2>
        </div>
        <div className="grid">
            {items.map(item => (
                <div key={item.id} className="credit-item-card">
                     <div style={{ display: 'flex', alignItems: 'center', margin: '0.5rem 0' }}>
                        {getCreditShopIcon(item.icon)}
                        <h3 style={{ margin: 0 }}>{item.name}</h3>
                    </div>
                     <p style={{ color: 'var(--text-secondary)', flexGrow: 1, margin: '0.5rem 0' }}>{item.description}</p>
                     <div className="price" style={{color: 'var(--primary)'}}>
                        {item.cost > 0 ? `${item.cost} ${item.unit || 'Crédits'}` : `Coût Dynamique`}
                     </div>
                     <small style={{color: 'var(--text-secondary)'}}>ID: {item.id}</small>
                </div>
            ))}
        </div>
    </div>
);

const TrophyIcon = () => (
    <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--gold)', marginRight: '0.5rem', flexShrink: 0 }}>
        <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>
        <path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/>
        <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>
    </svg>
);

const AchievementsCard = ({ title, achievements }) => (
    <div className="card">
        {title && (
            <div className="card-header">
                <h2 className="card-title">{title}</h2>
            </div>
        )}
        <div className="grid" style={{ padding: '1.5rem' }}>
            {achievements.map(a => (
                <div key={a.id} className="achievement-card">
                     <div style={{ display: 'flex', alignItems: 'center', marginBottom: '0.5rem' }}>
                        <TrophyIcon />
                        <h3 style={{ margin: 0, color: 'var(--gold)' }}>{a.name}</h3>
                     </div>
                     <p style={{ color: 'var(--text-secondary)', margin: '0.5rem 0 1rem 0' }}>{a.description}</p>
                     <p className="reward">Récompense: <strong>{a.reward_xp} XP</strong></p>
                </div>
            ))}
        </div>
    </div>
)

const EarningsSimulatorCard = ({ gamificationConfig }) => {
    const [userLevel, setUserLevel] = useState(10);
    const [affiliateSales, setAffiliateSales] = useState(200);
    const [referralCashout, setReferralCashout] = useState(50);
    
    const [isVip, setIsVip] = useState(false);
    const [vipMonths, setVipMonths] = useState(1);
    const [hasLoyaltyBonus, setHasLoyaltyBonus] = useState(false);
    const [weeklyBooster, setWeeklyBooster] = useState(0);
    const [guildBonus, setGuildBonus] = useState("none");

    const { creditsFromSales, creditsFromCashout, finalCommissionRate, isCapped } = useMemo(() => {
        if (!gamificationConfig) return { creditsFromSales: 0, creditsFromCashout: 0, finalCommissionRate: 0, isCapped: false };

        const affConfig = gamificationConfig.AFFILIATE_SYSTEM;
        const vipConfig = gamificationConfig.VIP_SYSTEM.PREMIUM;
        const guildConfig = gamificationConfig.GUILD_SYSTEM;
        
        // 1. Calcul du Taux de Commission sur Ventes
        let commissionRate = 0;
        let isResultCapped = false;
        
        if (guildBonus === 'top1') {
            commissionRate = guildConfig?.WEEKLY_REWARDS?.TOP_1?.commission_rate || 0.90;
        } else {
            // Taux de base
            let baseRate = 0;
            const sortedTiers = [...(affConfig.COMMISSION_TIERS || [])].sort((a,b) => b.level - a.level);
            for (const tier of sortedTiers) {
                if (userLevel >= tier.level) {
                    baseRate = tier.rate;
                    break;
                }
            }
            
            // Calcul des bonus
            let totalBoost = 0;
            if (isVip) {
                const sortedVipTiers = [...(vipConfig.COMMISSION_BONUS_TIERS || [])].sort((a,b) => b.consecutive_months - a.consecutive_months);
                for (const tier of sortedVipTiers) {
                    if (vipMonths >= tier.consecutive_months) {
                         totalBoost += tier.bonus;
                         break;
                    }
                }
            }
            if (hasLoyaltyBonus) {
                totalBoost += affConfig.PERMANENT_LOYALTY_BONUS?.RATE || 0;
            }
            totalBoost += weeklyBooster;
             if (guildBonus === 'top2') {
                totalBoost += guildConfig?.WEEKLY_REWARDS?.TOP_2?.commission_boost || 0;
            } else if (guildBonus === 'top3') {
                totalBoost += guildConfig?.WEEKLY_REWARDS?.TOP_3?.commission_boost || 0;
            }

            commissionRate = baseRate + totalBoost;

            // Plafond
            let cap = 1.0; // Pas de plafond par défaut
            if (guildBonus === 'top2') cap = guildConfig?.WEEKLY_REWARDS?.TOP_2?.max_commission_rate || 0.90;
            if (guildBonus === 'top3') cap = guildConfig?.WEEKLY_REWARDS?.TOP_3?.max_commission_rate || 0.90;
            
            if (commissionRate > cap) {
                commissionRate = cap;
                isResultCapped = true;
            }
        }
        
        const creditsFromSales = affiliateSales * commissionRate;
        
        // 2. Calcul de la Commission sur Cashout
        let cashoutCommRate = 0;
        const cashoutConfig = affConfig.CASHOUT_COMMISSION;

        if (guildBonus === 'top1' || guildBonus === 'top2' || guildBonus === 'top3') {
            cashoutCommRate = guildConfig?.WEEKLY_REWARDS?.TOP_1?.cashout_commission_rate || 0.10;
        } else if (isVip) {
            cashoutCommRate = cashoutConfig?.VIP_RATE || 0;
        } else {
            cashoutCommRate = cashoutConfig?.BASE_RATE || 0;
        }
        
        const creditsFromCashout = referralCashout * cashoutCommRate;

        return { 
            creditsFromSales: creditsFromSales.toFixed(2), 
            creditsFromCashout: creditsFromCashout.toFixed(2),
            finalCommissionRate: (commissionRate * 100).toFixed(1),
            isCapped: isResultCapped
        };
        
    }, [userLevel, affiliateSales, referralCashout, isVip, vipMonths, hasLoyaltyBonus, weeklyBooster, guildBonus, gamificationConfig]);

    if (!gamificationConfig) return null;

    return (
        <div className="card">
            <div className="card-header"><h2 className="card-title">Simulateur de Gains d'Affiliation</h2></div>
            
            <div className="simulator-grid wide">
                <div className="simulator-input">
                    <label htmlFor="sim-level">
                        <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19.5.5 12 12 .5l11.5 11.5Z"/></svg>
                        Votre Niveau
                    </label>
                    <input id="sim-level" type="range" min="1" max="50" value={userLevel} onChange={e => setUserLevel(Number(e.target.value))} />
                    <span>Niveau {userLevel}</span>
                </div>
                <div className="simulator-input">
                    <label htmlFor="sim-sales">
                        <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                        Ventes d'Affiliation (€)
                    </label>
                    <input id="sim-sales" type="range" min="0" max="1000" step="10" value={affiliateSales} onChange={e => setAffiliateSales(Number(e.target.value))} />
                    <span>{affiliateSales} €</span>
                </div>
                 <div className="simulator-input">
                    <label htmlFor="sim-cashout">
                        <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0-2 2c0 1.1.9 2 2 2a2 2 0 0 0 2-2c0-1.1-.9-2-2-2Z"/></svg>
                        Cashout d'un Filleul (€)
                    </label>
                    <input id="sim-cashout" type="range" min="0" max="500" step="5" value={referralCashout} onChange={e => setReferralCashout(Number(e.target.value))} />
                    <span>{referralCashout} €</span>
                </div>
            </div>

            <div className="simulator-grid">
                <div className="simulator-input">
                    <label htmlFor="sim-booster">
                        <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>
                        Booster Hebdomadaire
                    </label>
                    <select id="sim-booster" value={weeklyBooster} onChange={e => setWeeklyBooster(Number(e.target.value))}>
                        <option value="0">Aucun</option>
                        <option value={gamificationConfig.AFFILIATE_SYSTEM.WEEKLY_BOOSTERS.TOP_1_BOOST}>Top 1 (+{gamificationConfig.AFFILIATE_SYSTEM.WEEKLY_BOOSTERS.TOP_1_BOOST * 100}%)</option>
                        <option value={gamificationConfig.AFFILIATE_SYSTEM.WEEKLY_BOOSTERS.TOP_2_BOOST}>Top 2 (+{(gamificationConfig.AFFILIATE_SYSTEM.WEEKLY_BOOSTERS.TOP_2_BOOST * 100).toFixed(0)}%)</option>
                        <option value={gamificationConfig.AFFILIATE_SYSTEM.WEEKLY_BOOSTERS.TOP_3_BOOST}>Top 3 (+{gamificationConfig.AFFILIATE_SYSTEM.WEEKLY_BOOSTERS.TOP_3_BOOST * 100}%)</option>
                    </select>
                </div>
                <div className="simulator-input">
                    <label htmlFor="sim-guild">
                        <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v18"/><path d="M16 3v18"/><path d="M3 8h18"/><path d="M3 16h18"/></svg>
                        Bonus de Guilde
                    </label>
                    <select id="sim-guild" value={guildBonus} onChange={e => setGuildBonus(e.target.value)}>
                        <option value="none">Aucun</option>
                        <option value="top1">Top 1 Guilde (90% Comm + 10% Cashout)</option>
                        <option value="top2">Top 2 Guilde (+20% Comm + 10% Cashout)</option>
                        <option value="top3">Top 3 Guilde (+10% Comm + 10% Cashout)</option>
                    </select>
                </div>
            </div>

            <div className="simulator-checkbox-group">
                <div className="simulator-input-checkbox">
                    <input id="sim-vip" type="checkbox" checked={isVip} onChange={e => setIsVip(e.target.checked)} />
                    <label htmlFor="sim-vip">Membre VIP Premium</label>
                </div>
                <div className="simulator-input-checkbox">
                    <input id="sim-loyalty" type="checkbox" checked={hasLoyaltyBonus} onChange={e => setHasLoyaltyBonus(e.target.checked)} />
                    <label htmlFor="sim-loyalty">Bonus Fidélité (+5%)</label>
                </div>
            </div>

             {isVip && (
                <div className="simulator-input vip-slider">
                    <label htmlFor="sim-vip-months">Mois d'Ancienneté VIP (pour bonus progressif)</label>
                    <input id="sim-vip-months" type="range" min="1" max="12" value={vipMonths} onChange={e => setVipMonths(Number(e.target.value))} />
                    <span>{vipMonths} mois</span>
                </div>
            )}
            
            <div className="simulator-results">
                 <h3>Vos Gains Estimés</h3>
                 <div className="result-grid">
                    <div className="result-item">
                        <span>Gains sur Ventes</span>
                        <p>{creditsFromSales} crédits</p>
                    </div>
                    <div className="result-item">
                        <span>Commission sur Cashout</span>
                        <p>{creditsFromCashout} crédits</p>
                    </div>
                    <div className="result-item">
                        <span>Taux de Commission Final</span>
                        <p>{finalCommissionRate}% {isCapped && <span className="capped-label">(Plafonné)</span>}</p>
                    </div>
                    <div className="result-item total">
                        <span>Total des Gains</span>
                        <p>{(Number(creditsFromSales) + Number(creditsFromCashout)).toFixed(2)} crédits</p>
                    </div>
                 </div>
            </div>
        </div>
    );
};

const SkeletonCard = () => (
    <div className="skeleton-card">
        <div className="skeleton title"></div>
        <div className="skeleton text"></div>
        <div className="skeleton text"></div>
        <div className="skeleton text-short"></div>
    </div>
);

const ErrorCard = ({ onRetry }) => (
    <div className="card error-card">
        <h2 className="card-title">
            <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '0.5rem' }}>
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                <line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            Erreur de Chargement
        </h2>
        <p>Impossible de charger les données de configuration. Le tableau de bord est peut-être incomplet.</p>
        <button onClick={onRetry}>Réessayer</button>
    </div>
);


const App = () => {
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);
    
    const [config, setConfig] = useState(null);
    const [products, setProducts] = useState(null);
    const [achievements, setAchievements] = useState(null);
    const [creditShopItems, setCreditShopItems] = useState(null);

    const [productSearchTerm, setProductSearchTerm] = useState('');
    const [achievementsSearchTerm, setAchievementsSearchTerm] = useState('');

    const fetchAllData = useCallback(async () => {
        setIsLoading(true);
        setError(null);
        try {
            const [configRes, productsRes, achievementsRes, creditShopRes] = await Promise.all([
                fetch('/config.json'),
                fetch('/products.json'),
                fetch('/achievements_config.json'),
                fetch('/credit_shop_items.json')
            ]);
            
            if (!configRes.ok || !productsRes.ok || !achievementsRes.ok || !creditShopRes.ok) {
                throw new Error(`Un ou plusieurs fichiers n'ont pas pu être chargés (status: ${configRes.status}, ${productsRes.status}, etc.)`);
            }

            const [configData, productsData, achievementsData, creditShopData] = await Promise.all([
                configRes.json(),
                productsRes.json(),
                achievementsRes.json(),
                creditShopRes.json()
            ]);

            setConfig(configData);
            setProducts(productsData);
            setAchievements(achievementsData);
            setCreditShopItems(creditShopData);

        } catch (err) {
            console.error("Failed to fetch data:", err);
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchAllData();
    }, [fetchAllData]);

    const categorizedProducts = useMemo(() => {
        if (!products) return {};
        const filteredProducts = products.filter(p => {
            if (!productSearchTerm) return true;
            const searchTermLower = productSearchTerm.toLowerCase();
            return (
                p.name.toLowerCase().includes(searchTermLower) ||
                p.category.toLowerCase().includes(searchTermLower) ||
                p.description.toLowerCase().includes(searchTermLower)
            );
        });

        return filteredProducts.reduce((acc, p) => {
            const category = p.category || 'Non Catégorisé';
            if (!acc[category]) {
                acc[category] = [];
            }
            acc[category].push(p);
            return acc;
        }, {});
    }, [products, productSearchTerm]);

    const filteredAchievements = useMemo(() => {
        if (!achievements) return [];
        if (!achievementsSearchTerm) return achievements;
        const searchTermLower = achievementsSearchTerm.toLowerCase();
        return achievements.filter(a =>
            a.name.toLowerCase().includes(searchTermLower) ||
            a.description.toLowerCase().includes(searchTermLower)
        );
    }, [achievements, achievementsSearchTerm]);


    if (isLoading) {
        return (
            <>
                <h1>Dashboard Interactif ResellBoost</h1>
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard />
            </>
        );
    }

    if (error) {
        return (
             <>
                <h1>Dashboard Interactif ResellBoost</h1>
                <ErrorCard onRetry={fetchAllData} />
            </>
        );
    }

    return (
        <>
            <h1>Dashboard Interactif ResellBoost</h1>
            
            <JsonCard title="Configuration Globale (config.json)" data={config} />
            
            <EarningsSimulatorCard gamificationConfig={config.GAMIFICATION_CONFIG} />

            <div className="search-container">
                <h2>Produits</h2>
                <input
                    type="search"
                    placeholder="Rechercher par nom, catégorie, description..."
                    value={productSearchTerm}
                    onChange={e => setProductSearchTerm(e.target.value)}
                    className="search-input"
                />
            </div>
            {Object.keys(categorizedProducts).length > 0 ? (
                Object.entries(categorizedProducts).map(([category, productsInCategory]) => (
                    <ProductsCard key={category} title={category} products={productsInCategory} />
                ))
            ) : (
                 <div className="card" style={{padding: '1.5rem', textAlign: 'center'}}>
                    Aucun produit trouvé pour votre recherche.
                 </div>
            )}
            
            <CreditShopCard title="Boutique à Crédits" items={creditShopItems} />

            <div className="search-container">
                <h2>Tableau des Succès</h2>
                <input
                    type="search"
                    placeholder="Rechercher par nom, description..."
                    value={achievementsSearchTerm}
                    onChange={e => setAchievementsSearchTerm(e.target.value)}
                    className="search-input"
                />
            </div>
            {filteredAchievements.length > 0 ? (
                <AchievementsCard title="" achievements={filteredAchievements} />
            ) : (
                <div className="card" style={{padding: '1.5rem', textAlign: 'center'}}>
                    Aucun succès trouvé pour votre recherche.
                </div>
            )}
        </>
    );
};

const container = document.getElementById('root');
const root = createRoot(container);
root.render(<App />);