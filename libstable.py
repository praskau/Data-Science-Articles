"""
Python implementation of libstable - alpha-stable distribution computations.
Matches libstableR 1.0.2 (Royuela-del-Val et al., 2017 / Nolan 1997).

Public API:
    stable_pdf(x, pars, parametrization=0, tol=1e-12)
    stable_cdf(x, pars, parametrization=0, tol=1e-12)
    stable_q(p, pars, parametrization=0, tol=1e-12)
    stable_rnd(N, pars, parametrization=0, seed=None)
    stable_fit_init(rnd, parametrization=0)
    stable_fit_koutrouvelis(rnd, pars_init=None, parametrization=0)
    stable_fit_mle(rnd, pars_init=None, parametrization=0)
    stable_fit_mle2d(rnd, pars_init=None, parametrization=0)
"""

import numpy as np
from scipy import integrate, optimize, special, stats
from scipy.special import gammaln
from concurrent.futures import ThreadPoolExecutor
import warnings
import os
import math as _math

# ---------------------------------------------------------------------------
# Constants (matching stable_common.c)
# ---------------------------------------------------------------------------
_ALPHA_TH = 1.0e-3
_BETA_TH  = 1.0e-3
_XXI_TH   = 1.0e-5
_THETA_TH = 10.0 * np.finfo(float).eps
_INV_MAXITER = 15
_N_THREADS = min(12, os.cpu_count() or 1)

# Zone codes (matching C enum)
_STABLE  = 0
_ALPHA_1 = 1
_GAUSS   = 2
_CAUCHY  = 3
_LEVY    = 4

# ---------------------------------------------------------------------------
# Internal distribution descriptor
# ---------------------------------------------------------------------------
class _D:
    """Holds all precomputed values for a stable distribution."""
    __slots__ = ('alpha','beta','sigma','mu_0','mu_1','zone',
                 'alphainvalpha1','xi','theta0','k1','S','Vbeta1',
                 'c1','c2_part','c3','AUX1','AUX2',
                 'theta0_','beta_','xxipow','tol','rel','abst')


def _build(alpha, beta, sigma, mu, parametrization, tol):
    d = _D()
    d.tol = tol
    d.rel = tol
    d.abst = tol

    # --- zone ---
    if (2.0 - alpha) <= _ALPHA_TH:
        z = _GAUSS
    elif abs(alpha-0.5) <= _ALPHA_TH and abs(abs(beta)-1.0) <= _BETA_TH:
        z = _LEVY
    elif abs(alpha-1.0) <= _ALPHA_TH and abs(beta) <= _BETA_TH:
        z = _CAUCHY
    elif abs(alpha-1.0) <= _ALPHA_TH:
        z = _ALPHA_1
    else:
        z = _STABLE
    d.zone = z

    d.alpha = alpha
    d.beta  = beta
    d.sigma = sigma

    if z == _STABLE:
        a1 = alpha - 1.0
        d.alphainvalpha1 = alpha / a1
        d.xi     = -beta * np.tan(0.5 * alpha * np.pi)
        d.theta0 = np.arctan(-d.xi) / alpha
        d.k1     = -0.5 / a1 * np.log(1.0 + d.xi**2)
        d.S      = (1.0 + d.xi**2) ** (0.5 / alpha)
        d.Vbeta1 = d.k1 - d.alphainvalpha1*np.log(alpha) + np.log(abs(a1))
        if alpha < 1.0:
            d.c1      = 0.5 - d.theta0 / np.pi
            d.c2_part = alpha / ((1.0 - alpha) * np.pi)
            d.c3      = 1.0 / np.pi
            d.AUX1    = np.log(tol)
            d.AUX2    = np.log(np.log(8.5358 / tol) / 0.9599)
        else:
            d.c1      = 1.0
            d.c2_part = alpha / (a1 * np.pi)
            d.c3      = -1.0 / np.pi
            d.AUX1    = np.log(np.log(8.5358 / tol) / 0.9599)
            d.AUX2    = np.log(tol)

    elif z == _ALPHA_1:
        d.alpha          = 1.0
        d.alphainvalpha1 = 0.0
        d.xi             = 0.0
        d.theta0         = np.pi / 2
        d.k1             = np.log(2.0 / np.pi)
        d.S              = 2.0 / np.pi
        d.c1             = 0.0
        d.c3             = 1.0 / np.pi
        d.Vbeta1         = 2.0 / (np.pi * np.e)
        d.c2_part        = 0.5 / abs(beta)
        if beta < 0:
            d.AUX1 = np.log(np.log(8.5358 / tol) / 0.9599)
            d.AUX2 = np.log(tol)
        else:
            d.AUX1 = np.log(tol)
            d.AUX2 = np.log(np.log(8.5358 / tol) / 0.9599)

    elif z == _CAUCHY:
        d.alpha = 1.0; d.beta = 0.0
        d.alphainvalpha1 = 0.0; d.xi = 0.0
        d.theta0 = np.pi/2; d.k1 = np.log(2.0/np.pi)
        d.S = 2.0/np.pi; d.c1 = 0.0; d.c3 = 1.0/np.pi
        d.Vbeta1 = 2.0/(np.pi*np.e); d.c2_part = 0.0
        d.AUX1 = np.log(1e-6); d.AUX2 = np.log(18.0)

    elif z == _GAUSS:
        d.alpha = 2.0; d.beta = 0.0
        d.alphainvalpha1 = 2.0; d.xi = 0.0; d.theta0 = 0.0
        d.k1 = np.log(2.0); d.S = 2.0; d.c1 = 1.0
        d.c2_part = 2.0/np.pi; d.c3 = -1.0/np.pi; d.Vbeta1 = 0.25
        d.AUX1 = np.log(1e-6); d.AUX2 = np.log(18.0)

    elif z == _LEVY:
        d.alpha          = 0.5
        d.beta           = 1.0 if beta > 0 else -1.0
        d.alphainvalpha1 = -1.0
        d.xi             = -d.beta
        d.theta0         = np.pi / 2
        d.k1             = 0.0; d.S = 1.0; d.c1 = 0.0
        d.c2_part        = 0.5 / np.pi; d.c3 = 1.0 / np.pi
        d.Vbeta1         = d.k1 - (-1.0)*np.log(0.5) + np.log(0.5)
        d.AUX1 = np.log(1e-6); d.AUX2 = np.log(18.0)

    # location
    if parametrization == 0:
        d.mu_0 = mu
        if d.alpha == 1:
            d.mu_1 = mu - d.beta*(2.0/np.pi)*sigma*np.log(sigma)
        else:
            d.mu_1 = mu + d.xi*sigma
    else:
        d.mu_1 = mu
        if d.alpha == 1:
            d.mu_0 = mu + d.beta*(2.0/np.pi)*sigma*np.log(sigma)
        else:
            d.mu_0 = mu - d.xi*sigma

    d.theta0_ = d.theta0
    d.beta_   = d.beta
    d.xxipow  = 0.0
    return d


def _copy(d):
    nd = _D()
    for s in _D.__slots__:
        setattr(nd, s, getattr(d, s))
    return nd


# ---------------------------------------------------------------------------
# Integrand functions  (matching stable_pdf.c / stable_cdf.c exactly)
# ---------------------------------------------------------------------------

def _aux2(theta, alpha, theta0_, a1a1, k1, xxipow):
    """Log-inner body for STABLE zone (g_aux2). Max of PDF/CDF integrand at 0."""
    ct  = np.cos(theta)
    aux = (theta0_ + theta) * alpha
    sa  = np.sin(aux)
    cam = np.cos(aux - theta)
    if sa <= 0.0 or cam <= 0.0 or ct <= 0.0:
        return np.nan
    return a1a1 * np.log(ct / sa) + np.log(cam / ct) + k1 + xxipow


def _pdf_g2(theta, alpha, theta0_, a1a1, k1, xxipow):
    """PDF integrand for STABLE zone (stable_pdf_g2)."""
    lg = _aux2(theta, alpha, theta0_, a1a1, k1, xxipow)
    if np.isnan(lg) or lg > 6.55 or lg < -700.0:
        return 0.0
    g = np.exp(lg)
    r = np.exp(-g) * g
    return r if (np.isfinite(r) and r >= 0.0) else 0.0


def _cdf_g2(theta, alpha, theta0_, a1a1, k1, xxipow):
    """CDF integrand for STABLE zone (stable_cdf_g2)."""
    lg = _aux2(theta, alpha, theta0_, a1a1, k1, xxipow)
    if np.isnan(lg) or lg > 700.0:
        return 0.0
    ge = np.exp(lg)
    if ge < 1.522e-8:
        return 1.0 - ge
    return np.exp(-ge)


def _aux1(theta, beta_, k1, xxipow):
    """Log-inner body for ALPHA_1 zone (g_aux1)."""
    ct  = np.cos(theta)
    aux = (beta_ * theta + np.pi * 0.5) / ct
    if aux <= 0.0:
        return np.nan
    return np.sin(theta)*aux/beta_ + np.log(aux) + k1 + xxipow


def _pdf_g1(theta, beta_, k1, xxipow):
    """PDF integrand for ALPHA_1 zone (stable_pdf_g1)."""
    lg = _aux1(theta, beta_, k1, xxipow)
    if np.isnan(lg):
        return 0.0
    g = np.exp(lg)
    if g < 1.522e-8:
        return (1.0 - g) * g
    r = np.exp(-g) * g
    return r if (np.isfinite(r) and r >= 0.0) else 0.0


def _cdf_g1(theta, beta_, k1, xxipow):
    """CDF integrand for ALPHA_1 zone (stable_cdf_g1)."""
    lg = _aux1(theta, beta_, k1, xxipow)
    if np.isnan(lg):
        return 0.0
    ge = np.exp(lg)
    if ge < 1.522e-8:
        return 1.0 - ge
    return np.exp(-ge)


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------

_BRENT_RTOL = 4.0 * np.finfo(float).eps

def _brentq(f, args, a, b, xtol):
    """Brent root-finding; returns (root, status) where status=0=OK,-1=border."""
    fa = f(a, *args)
    fb = f(b, *args)
    if np.isnan(fa) or np.isnan(fb):
        return (a+b)*0.5, -3
    if fa*fb > 0.0:
        return (a, -2) if abs(fa) < abs(fb) else (b, -1)
    try:
        r = optimize.brentq(f, a, b, args=args, xtol=xtol,
                            rtol=_BRENT_RTOL, maxiter=200)
        return r, 0
    except Exception:
        return (a+b)*0.5, -3


def _quad(f, a, b, args, epsabs, epsrel):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        val, _ = integrate.quad(f, a, b, args=args,
                                epsabs=epsabs, epsrel=epsrel, limit=1000)
    return abs(val)


# ---------------------------------------------------------------------------
# Numba fast path  (enabled when numba is installed)
# ---------------------------------------------------------------------------
# Implements the full hot path (Brent + 64-pt Gauss-Legendre) in JIT-compiled
# native code with prange parallelism, giving ~10-50x speedup over scipy quad.

_NB_AVAILABLE = False
try:
    from numba import njit, prange

    _GL_NODES_NB, _GL_WEIGHTS_NB = np.polynomial.legendre.leggauss(128)
    _GL_NODES_NB  = _GL_NODES_NB.astype(np.float64)
    _GL_WEIGHTS_NB = _GL_WEIGHTS_NB.astype(np.float64)

    # --- Aux (log-body) functions ---

    @njit(cache=True, fastmath=True)
    def _nb_aux2(theta, alpha, theta0_, a1a1, k1, xxipow):
        ct  = _math.cos(theta)
        aux = (theta0_ + theta) * alpha
        sa  = _math.sin(aux)
        cam = _math.cos(aux - theta)
        if sa <= 0.0 or cam <= 0.0 or ct <= 0.0:
            return _math.nan
        return a1a1 * _math.log(ct/sa) + _math.log(cam/ct) + k1 + xxipow

    @njit(cache=True, fastmath=True)
    def _nb_aux1(theta, beta_, k1, xxipow):
        ct  = _math.cos(theta)
        aux = (beta_ * theta + _math.pi * 0.5) / ct
        if aux <= 0.0:
            return _math.nan
        return _math.sin(theta)*aux/beta_ + _math.log(aux) + k1 + xxipow

    # --- Integrand functions ---

    @njit(cache=True, fastmath=True)
    def _nb_pdf_g2(theta, alpha, theta0_, a1a1, k1, xxipow):
        lg = _nb_aux2(theta, alpha, theta0_, a1a1, k1, xxipow)
        if _math.isnan(lg) or lg > 6.55 or lg < -700.0:
            return 0.0
        g = _math.exp(lg)
        r = _math.exp(-g) * g
        return r if (_math.isfinite(r) and r >= 0.0) else 0.0

    @njit(cache=True, fastmath=True)
    def _nb_cdf_g2(theta, alpha, theta0_, a1a1, k1, xxipow):
        lg = _nb_aux2(theta, alpha, theta0_, a1a1, k1, xxipow)
        if _math.isnan(lg):
            return 0.0
        ge = _math.exp(lg)
        if ge < 1.522e-8:
            return 1.0 - ge
        return _math.exp(-ge)

    @njit(cache=True, fastmath=True)
    def _nb_pdf_g1(theta, beta_, k1, xxipow):
        lg = _nb_aux1(theta, beta_, k1, xxipow)
        if _math.isnan(lg):
            return 0.0
        g = _math.exp(lg)
        if g < 1.522e-8:
            return (1.0 - g) * g
        r = _math.exp(-g) * g
        return r if (_math.isfinite(r) and r >= 0.0) else 0.0

    @njit(cache=True, fastmath=True)
    def _nb_cdf_g1(theta, beta_, k1, xxipow):
        lg = _nb_aux1(theta, beta_, k1, xxipow)
        if _math.isnan(lg):
            return 0.0
        ge = _math.exp(lg)
        if ge < 1.522e-8:
            return 1.0 - ge
        return _math.exp(-ge)

    # --- GL quadrature per subinterval ---

    @njit(cache=True, fastmath=True)
    def _nb_gl_pdf_g2(alpha, theta0_, a1a1, k1, xxipow, a, b, nodes, weights):
        s = 0.0; half = (b-a)*0.5; mid = (b+a)*0.5
        for i in range(len(nodes)):
            t = mid + half*nodes[i]
            s += weights[i] * _nb_pdf_g2(t, alpha, theta0_, a1a1, k1, xxipow)
        return abs(s * half)

    @njit(cache=True, fastmath=True)
    def _nb_gl_cdf_g2(alpha, theta0_, a1a1, k1, xxipow, a, b, nodes, weights):
        s = 0.0; half = (b-a)*0.5; mid = (b+a)*0.5
        for i in range(len(nodes)):
            t = mid + half*nodes[i]
            s += weights[i] * _nb_cdf_g2(t, alpha, theta0_, a1a1, k1, xxipow)
        return s * half

    @njit(cache=True, fastmath=True)
    def _nb_gl_pdf_g1(beta_, k1, xxipow, a, b, nodes, weights):
        s = 0.0; half = (b-a)*0.5; mid = (b+a)*0.5
        for i in range(len(nodes)):
            t = mid + half*nodes[i]
            s += weights[i] * _nb_pdf_g1(t, beta_, k1, xxipow)
        return abs(s * half)

    @njit(cache=True, fastmath=True)
    def _nb_gl_cdf_g1(beta_, k1, xxipow, a, b, nodes, weights):
        s = 0.0; half = (b-a)*0.5; mid = (b+a)*0.5
        for i in range(len(nodes)):
            t = mid + half*nodes[i]
            s += weights[i] * _nb_cdf_g1(t, beta_, k1, xxipow)
        return s * half

    # --- Brent's method (JIT compiled, no GIL) ---

    @njit(cache=True)
    def _nb_brent_g2(alpha, theta0_, a1a1, k1, xxipow, a, b, xtol, target):
        """Find root of (_nb_aux2 - target) in [a,b]. Returns (root, ok)."""
        fa = _nb_aux2(a, alpha, theta0_, a1a1, k1, xxipow) - target
        fb = _nb_aux2(b, alpha, theta0_, a1a1, k1, xxipow) - target
        if _math.isnan(fa) or _math.isnan(fb):
            return (a+b)*0.5, False
        if fa*fb > 0.0:
            return (a if abs(fa)<abs(fb) else b), False
        if abs(fa) < abs(fb):
            a, b = b, a; fa, fb = fb, fa
        c = a; fc = fa; mflag = True; d = 0.0
        for _ in range(200):
            if abs(fb) < xtol or abs(b-a) < xtol:
                return b, True
            if fa != fc and fb != fc:
                s = (a*fb*fc/((fa-fb)*(fa-fc)) +
                     b*fa*fc/((fb-fa)*(fb-fc)) +
                     c*fa*fb/((fc-fa)*(fc-fb)))
            else:
                s = b - fb*(b-a)/(fb-fa)
            tmp1 = (3*a+b)/4
            cond = not (tmp1 < s < b) if tmp1 < b else not (b < s < tmp1)
            if (cond or (mflag and abs(s-b)>=abs(b-c)/2) or
                    (not mflag and abs(s-b)>=abs(c-d)/2) or
                    (mflag and abs(b-c)<xtol) or
                    (not mflag and abs(c-d)<xtol)):
                s = (a+b)/2; mflag = True
            else:
                mflag = False
            fs = _nb_aux2(s, alpha, theta0_, a1a1, k1, xxipow) - target
            d = c; c = b; fc = fb
            if fa*fs < 0:
                b = s; fb = fs
            else:
                a = s; fa = fs
            if abs(fa) < abs(fb):
                a, b = b, a; fa, fb = fb, fa
        return b, True

    @njit(cache=True)
    def _nb_brent_g1(beta_, k1, xxipow, a, b, xtol, target):
        """Find root of (_nb_aux1 - target) in [a,b]. Returns (root, ok)."""
        fa = _nb_aux1(a, beta_, k1, xxipow) - target
        fb = _nb_aux1(b, beta_, k1, xxipow) - target
        if _math.isnan(fa) or _math.isnan(fb):
            return (a+b)*0.5, False
        if fa*fb > 0.0:
            return (a if abs(fa)<abs(fb) else b), False
        if abs(fa) < abs(fb):
            a, b = b, a; fa, fb = fb, fa
        c = a; fc = fa; mflag = True; d = 0.0
        for _ in range(200):
            if abs(fb) < xtol or abs(b-a) < xtol:
                return b, True
            if fa != fc and fb != fc:
                s = (a*fb*fc/((fa-fb)*(fa-fc)) +
                     b*fa*fc/((fb-fa)*(fb-fc)) +
                     c*fa*fb/((fc-fa)*(fc-fb)))
            else:
                s = b - fb*(b-a)/(fb-fa)
            tmp1 = (3*a+b)/4
            cond = not (tmp1 < s < b) if tmp1 < b else not (b < s < tmp1)
            if (cond or (mflag and abs(s-b)>=abs(b-c)/2) or
                    (not mflag and abs(s-b)>=abs(c-d)/2) or
                    (mflag and abs(b-c)<xtol) or
                    (not mflag and abs(c-d)<xtol)):
                s = (a+b)/2; mflag = True
            else:
                mflag = False
            fs = _nb_aux1(s, beta_, k1, xxipow) - target
            d = c; c = b; fc = fb
            if fa*fs < 0:
                b = s; fb = fs
            else:
                a = s; fa = fs
            if abs(fa) < abs(fb):
                a, b = b, a; fa, fb = fb, fa
        return b, True

    # --- Full PDF/CDF point evaluation ---

    @njit(cache=True)
    def _nb_integrate_pdf_stable(alpha, theta0_, a1a1, k1, xxipow, AUX1, AUX2,
                                  nodes, weights):
        """4-subinterval PDF integration for STABLE zone."""
        TH = 10.0 * 2.220446049250313e-16
        PI_2 = _math.pi * 0.5
        th0 = -theta0_ + TH; th4 = PI_2 - TH
        xtol = 1e-9 * (th4 - th0)

        peak, ok = _nb_brent_g2(alpha, theta0_, a1a1, k1, xxipow, th0, th4, xtol, 0.0)

        if ok:
            a0 = _nb_aux2(th0, alpha, theta0_, a1a1, k1, xxipow)
            a4 = _nb_aux2(th4, alpha, theta0_, a1a1, k1, xxipow)
            # left threshold
            if _math.isnan(a0) or abs(AUX1) > abs(a0):
                t1 = th0 + 0.01*(peak-th0)
            else:
                t1, _ = _nb_brent_g2(alpha, theta0_, a1a1, k1, xxipow,
                                      th0, peak, 1e-9*(peak-th0), AUX1)
            # right threshold
            if _math.isnan(a4) or abs(AUX2) > abs(a4):
                t3 = th4 - 0.01*(th4-peak)
            else:
                t3, _ = _nb_brent_g2(alpha, theta0_, a1a1, k1, xxipow,
                                      peak, th4, 1e-9*(th4-peak), AUX2)
            if peak - t1 < t3 - peak:
                t2 = 2.0*peak - t1
            else:
                th0, th4 = th4, th0; t1, t3 = t3, t1; t2 = 2.0*peak - t1
            p1 = _nb_gl_pdf_g2(alpha, theta0_, a1a1, k1, xxipow, t1, t2, nodes, weights)
            p2 = _nb_gl_pdf_g2(alpha, theta0_, a1a1, k1, xxipow, t2, t3, nodes, weights)
            p3 = _nb_gl_pdf_g2(alpha, theta0_, a1a1, k1, xxipow, t3, th4, nodes, weights)
            p4 = _nb_gl_pdf_g2(alpha, theta0_, a1a1, k1, xxipow, th0, t1, nodes, weights)
            return p4 + p3 + p2 + p1
        else:
            t2 = (th0+th4)*0.5
            return (_nb_gl_pdf_g2(alpha, theta0_, a1a1, k1, xxipow, th0, t2, nodes, weights) +
                    _nb_gl_pdf_g2(alpha, theta0_, a1a1, k1, xxipow, t2, th4, nodes, weights))

    @njit(cache=True)
    def _nb_integrate_cdf_stable(alpha, theta0_, a1a1, k1, xxipow, alpha_gt1,
                                  nodes, weights):
        """2-subinterval CDF integration for STABLE zone."""
        TH5 = 10.0 * 2.220446049250313e-16 / 5
        PI_2 = _math.pi * 0.5
        th0 = -theta0_ + TH5; thS = PI_2 - TH5

        if alpha_gt1:
            gS = _nb_cdf_g2(thS, alpha, theta0_, a1a1, k1, xxipow)
            target = -_math.log(max(gS, 1e-300) * 1e-2)
            t1, ok = _nb_brent_g2(alpha, theta0_, a1a1, k1, xxipow,
                                   th0, thS, 1e-9*(thS-th0), target)
            if not ok:
                t1 = (th0+thS)*0.5
            v0 = _nb_gl_cdf_g2(alpha, theta0_, a1a1, k1, xxipow, t1, thS, nodes, weights)
            v1 = _nb_gl_cdf_g2(alpha, theta0_, a1a1, k1, xxipow, th0, t1, nodes, weights)
            return v0 + v1
        else:
            g0 = _nb_cdf_g2(th0, alpha, theta0_, a1a1, k1, xxipow)
            target = -_math.log(max(g0, 1e-300) * 1e-2)
            t1, ok = _nb_brent_g2(alpha, theta0_, a1a1, k1, xxipow,
                                   th0, thS, 1e-9*(thS-th0), target)
            if not ok:
                t1 = (th0+thS)*0.5
            v0 = _nb_gl_cdf_g2(alpha, theta0_, a1a1, k1, xxipow, th0, t1, nodes, weights)
            v1 = _nb_gl_cdf_g2(alpha, theta0_, a1a1, k1, xxipow, t1, thS, nodes, weights)
            return v0 + v1

    @njit(cache=True)
    def _nb_integrate_pdf_alpha1(beta_, k1, xxipow, AUX1, AUX2, nodes, weights):
        """4-subinterval PDF integration for ALPHA_1 zone."""
        TH = 10.0 * 2.220446049250313e-16
        PI_2 = _math.pi * 0.5
        th0 = -PI_2 + TH; th4 = PI_2 - TH
        xtol = 1e-9 * (th4 - th0)

        peak, ok = _nb_brent_g1(beta_, k1, xxipow, th0, th4, xtol, 0.0)

        if ok:
            a0 = _nb_aux1(th0, beta_, k1, xxipow)
            a4 = _nb_aux1(th4, beta_, k1, xxipow)
            if _math.isnan(a0) or abs(AUX1) > abs(a0):
                t1 = th0 + 0.01*(peak-th0)
            else:
                t1, _ = _nb_brent_g1(beta_, k1, xxipow, th0, peak, 1e-9*(peak-th0), AUX1)
            if _math.isnan(a4) or abs(AUX2) > abs(a4):
                t3 = th4 - 0.01*(th4-peak)
            else:
                t3, _ = _nb_brent_g1(beta_, k1, xxipow, peak, th4, 1e-9*(th4-peak), AUX2)
            if peak - t1 < t3 - peak:
                t2 = 2.0*peak - t1
            else:
                th0, th4 = th4, th0; t1, t3 = t3, t1; t2 = 2.0*peak - t1
            p1 = _nb_gl_pdf_g1(beta_, k1, xxipow, t1, t2, nodes, weights)
            p2 = _nb_gl_pdf_g1(beta_, k1, xxipow, t2, t3, nodes, weights)
            p3 = _nb_gl_pdf_g1(beta_, k1, xxipow, t3, th4, nodes, weights)
            p4 = _nb_gl_pdf_g1(beta_, k1, xxipow, th0, t1, nodes, weights)
            return p4 + p3 + p2 + p1
        else:
            t2 = (th0+th4)*0.5
            return (_nb_gl_pdf_g1(beta_, k1, xxipow, th0, t2, nodes, weights) +
                    _nb_gl_pdf_g1(beta_, k1, xxipow, t2, th4, nodes, weights))

    @njit(cache=True)
    def _nb_integrate_cdf_alpha1(beta_, k1, xxipow, beta_gt0, nodes, weights):
        """2-subinterval CDF integration for ALPHA_1 zone."""
        TH5 = 10.0 * 2.220446049250313e-16 / 5
        PI_2 = _math.pi * 0.5
        th0 = -PI_2 + TH5; thS = PI_2 - TH5

        if beta_gt0:
            g0 = _nb_cdf_g1(th0, beta_, k1, xxipow)
            target = -_math.log(max(g0, 1e-300) * 1e-2)
            t1, ok = _nb_brent_g1(beta_, k1, xxipow, th0, thS, 1e-9*(thS-th0), target)
            if not ok:
                t1 = (th0+thS)*0.5
            v0 = _nb_gl_cdf_g1(beta_, k1, xxipow, th0, t1, nodes, weights)
            v1 = _nb_gl_cdf_g1(beta_, k1, xxipow, t1, thS, nodes, weights)
            return v0 + v1
        else:
            gS = _nb_cdf_g1(thS, beta_, k1, xxipow)
            target = -_math.log(max(gS, 1e-300) * 1e-2)
            t1, ok = _nb_brent_g1(beta_, k1, xxipow, th0, thS, 1e-9*(thS-th0), target)
            if not ok:
                t1 = (th0+thS)*0.5
            v0 = _nb_gl_cdf_g1(beta_, k1, xxipow, t1, thS, nodes, weights)
            v1 = _nb_gl_cdf_g1(beta_, k1, xxipow, th0, t1, nodes, weights)
            return v0 + v1

    # --- Vectorised parallel PDF / CDF ---

    @njit(parallel=True, cache=True)
    def _nb_pdf_array(x_arr,
                      zone, alpha, beta, sigma, mu_0, xi,
                      theta0, alphainvalpha1, k1, c2_part,
                      AUX1, AUX2, nodes, weights):
        """Parallel PDF for all zone types (returns raw integral, not yet scaled)."""
        n = len(x_arr)
        out = np.empty(n)
        for i in prange(n):
            x = x_arr[i]
            if zone == 2:   # _GAUSS
                x_ = (x - mu_0) / sigma
                out[i] = 0.5 * _math.sqrt(1.0/_math.pi) / sigma * _math.exp(-x_*x_*0.25)
                continue
            if zone == 3:   # _CAUCHY
                x_ = (x - mu_0) / sigma
                out[i] = (1.0/_math.pi) / (1.0 + x_*x_) / sigma
                continue
            if zone == 4:   # _LEVY
                xxi = (x - mu_0) / sigma - xi
                if xxi > 0.0 and beta > 0.0:
                    out[i] = (_math.sqrt(sigma*0.5/_math.pi) *
                              _math.exp(-sigma*0.5/(xxi*sigma)) /
                              (xxi*sigma)**1.5)
                elif xxi < 0.0 and beta < 0.0:
                    axxi = abs(xxi)
                    out[i] = (_math.sqrt(sigma*0.5/_math.pi) *
                              _math.exp(-sigma*0.5/(axxi*sigma)) /
                              (axxi*sigma)**1.5)
                else:
                    out[i] = 0.0
                continue
            if zone == 1:   # _ALPHA_1
                x_ = (x - mu_0) / sigma
                beta_ = beta if beta >= 0.0 else -beta
                x_s   = x_ if beta >= 0.0 else -x_
                xp = -_math.pi * x_s * c2_part
                integral = _nb_integrate_pdf_alpha1(beta_, k1, xp, AUX1, AUX2,
                                                     nodes, weights)
                out[i] = c2_part * integral / sigma
                continue
            # _STABLE zone
            x_  = (x - mu_0) / sigma
            xxi = x_ - xi
            XXI_TH = 1.0e-5
            if abs(xxi) <= XXI_TH:
                g1a1 = _math.lgamma(1.0 + 1.0/alpha)
                th0v = theta0
                Sv   = (1.0 + xi*xi)**(0.5/alpha)
                out[i] = _math.exp(g1a1) * _math.cos(th0v) / (_math.pi * Sv) / sigma
                continue
            flip = xxi < 0.0
            axxi = abs(xxi)
            theta0_ = -theta0 if flip else theta0
            THETA_TH2 = 10.0 * 2.220446049250313e-16
            if abs(theta0_ + _math.pi*0.5) < 2*THETA_TH2:
                out[i] = 0.0
                continue
            xp = alphainvalpha1 * _math.log(axxi)
            integral = _nb_integrate_pdf_stable(alpha, theta0_, alphainvalpha1,
                                                 k1, xp, AUX1, AUX2, nodes, weights)
            out[i] = c2_part / axxi * integral / sigma

        return out

    @njit(parallel=True, cache=True)
    def _nb_cdf_array(x_arr,
                      zone, alpha, beta, sigma, mu_0, xi,
                      theta0, alphainvalpha1, k1, c1, c2_part, c3,
                      nodes, weights):
        """Parallel CDF for all zone types."""
        n = len(x_arr)
        out = np.empty(n)
        for i in prange(n):
            x = x_arr[i]
            if zone == 2:   # _GAUSS
                x_ = (x - mu_0) / sigma
                out[i] = 0.5 + 0.5 * _math.erf(x_ * 0.5)
                continue
            if zone == 3:   # _CAUCHY
                x_ = (x - mu_0) / sigma
                out[i] = 0.5 + (1.0/_math.pi) * _math.atan(x_)
                continue
            if zone == 4:   # _LEVY
                xxi = (x - mu_0) / sigma - xi
                if xxi > 0.0 and beta > 0.0:
                    out[i] = _math.erfc(_math.sqrt(0.5/xxi))
                elif xxi < 0.0 and beta < 0.0:
                    out[i] = _math.erfc(_math.sqrt(-0.5/xxi))
                else:
                    out[i] = 0.0
                continue
            if zone == 1:   # _ALPHA_1
                x_ = (x - mu_0) / sigma
                beta_ = beta if beta >= 0.0 else -beta
                x_s   = x_ if beta >= 0.0 else -x_
                xp = -_math.pi * x_s * 0.5 / beta_
                beta_gt0 = beta >= 0.0
                integral = _nb_integrate_cdf_alpha1(beta_, k1, xp, beta_gt0,
                                                     nodes, weights)
                out[i] = c3*integral if beta >= 0.0 else 1.0 - c3*integral
                continue
            # _STABLE zone
            x_  = (x - mu_0) / sigma
            xxi = x_ - xi
            XXI_TH = 1.0e-5
            if abs(xxi) < XXI_TH:
                out[i] = (1.0/_math.pi) * (_math.pi*0.5 - theta0)
                continue
            flip = xxi < 0.0
            theta0_ = -theta0 if flip else theta0
            THETA_TH2 = 10.0 * 2.220446049250313e-16
            if abs(theta0_ + _math.pi*0.5) < THETA_TH2:
                out[i] = 0.0 if flip else 1.0
                continue
            alpha_gt1 = alpha > 1.0
            cdf_eff = _nb_integrate_cdf_stable(alpha, theta0_, alphainvalpha1,
                                                k1, alphainvalpha1*_math.log(abs(xxi)),
                                                alpha_gt1, nodes, weights)
            if not flip:
                out[i] = c1 + c3 * cdf_eff
            elif alpha > 1.0:
                out[i] = -c3 * cdf_eff
            else:
                out[i] = 0.5 - (theta0 + cdf_eff) / _math.pi

        return out

    _NB_AVAILABLE = True

except Exception:
    _NB_AVAILABLE = False


# ---------------------------------------------------------------------------
# PDF integration  (matching stable_integration_pdf in stable_pdf.c)
# ---------------------------------------------------------------------------

def _integrate_pdf(d):
    tol   = d.rel
    abst  = d.abst
    PI_2  = np.pi * 0.5
    th0   = -d.theta0_ + _THETA_TH
    th4   = PI_2 - _THETA_TH

    if d.zone == _ALPHA_1:
        pdf_f = _pdf_g1; aux_f = _aux1
        args  = (d.beta_, d.k1, d.xxipow)
    else:
        pdf_f = _pdf_g2; aux_f = _aux2
        args  = (d.alpha, d.theta0_, d.alphainvalpha1, d.k1, d.xxipow)

    # Find maximum (aux=0)
    peak, case = _brentq(aux_f, args, th0, th4, 1e-9*(th4-th0))

    if case == 0:
        # --- interior maximum: 4-subinterval strategy ---
        a0 = aux_f(th0, *args); a4 = aux_f(th4, *args)

        # left threshold (AUX1)
        try:
            if np.isnan(a0) or abs(d.AUX1) > abs(a0):
                t1 = th0 + 1e-2*(peak - th0)
            else:
                t1, _ = _brentq(lambda t,*a: aux_f(t,*a)-d.AUX1, args,
                                 th0, peak, 1e-9*(peak-th0))
        except Exception:
            t1 = th0 + 1e-2*(peak - th0)

        # right threshold (AUX2)
        try:
            if np.isnan(a4) or abs(d.AUX2) > abs(a4):
                t3 = th4 - 1e-2*(th4 - peak)
            else:
                t3, _ = _brentq(lambda t,*a: aux_f(t,*a)-d.AUX2, args,
                                 peak, th4, 1e-9*(th4-peak))
        except Exception:
            t3 = th4 - 1e-2*(th4 - peak)

        # symmetric interval around peak
        if peak - t1 < t3 - peak:
            t2 = 2.0*peak - t1
        else:
            th0, th4 = th4, th0
            t1, t3   = t3, t1
            t2       = 2.0*peak - t1

        p1 = _quad(pdf_f, t1, t2, args, abst, tol)
        p2 = _quad(pdf_f, t2, t3, args, max(p1*tol,abst)*0.25, tol)
        p3 = _quad(pdf_f, t3, th4, args, max((p2+p1)*tol,abst)*0.25, tol)
        p4 = _quad(pdf_f, th0, t1, args, max((p3+p2+p1)*tol,abst)*0.25, tol)
        return p4 + p3 + p2 + p1

    elif case == -2:
        # max at left border
        pv = pdf_f(th0, *args)
        try:
            t2, _ = _brentq(lambda t,*a: pdf_f(t,*a)-pv*1e-6, args,
                             th0, th4, 1e-9*(th4-th0))
        except Exception:
            t2 = (th0+th4)*0.5
        return (_quad(pdf_f, th0, t2, args, abst, tol) +
                _quad(pdf_f, t2,  th4, args, abst, tol))

    else:
        # max at right border
        pv = pdf_f(th4, *args)
        try:
            t2, _ = _brentq(lambda t,*a: pdf_f(t,*a)-pv*1e-6, args,
                             th0, th4, 1e-9*(th4-th0))
        except Exception:
            t2 = (th0+th4)*0.5
        return (_quad(pdf_f, th0, t2, args, abst, tol) +
                _quad(pdf_f, t2,  th4, args, abst, tol))


# ---------------------------------------------------------------------------
# CDF integration  (matching stable_integration_cdf in stable_cdf.c)
# ---------------------------------------------------------------------------

def _integrate_cdf(d):
    tol  = d.rel
    abst = d.abst
    SUBS = 2
    PI_2 = np.pi * 0.5
    th0  = -d.theta0_ + _THETA_TH / 5
    thS  = PI_2 - _THETA_TH / 5

    if d.zone == _ALPHA_1:
        cdf_f = _cdf_g1; aux_f = _aux1
        args  = (d.beta_, d.k1, d.xxipow)
    else:
        cdf_f = _cdf_g2; aux_f = _aux2
        args  = (d.alpha, d.theta0_, d.alphainvalpha1, d.k1, d.xxipow)

    # Evaluate CDF integrand at endpoints
    g0 = cdf_f(th0, *args)
    gS = cdf_f(thS, *args)

    total = 0.0

    max_at_right = (d.alpha > 1.0 or (d.alpha == 1.0 and d.beta_ < 0))

    if max_at_right:
        # k goes SUBS-1 down to 0: find split then integrate right-to-left
        thetas = [th0, None, thS]
        gvals  = [g0,  None, gS ]
        # Find theta[1] where integrand drops to ~1% of value at thS
        gend    = max(gS, 1e-300)
        target  = -np.log(gend * 1e-2)          # = exp(aux_at_thS) + log(100)
        try:
            t1, _ = _brentq(lambda t,*a: aux_f(t,*a)-target, args,
                             th0, thS, 1e-9*(thS-th0))
        except Exception:
            t1 = (th0+thS)*0.5
        thetas[1] = t1
        gvals[1]  = cdf_f(t1, *args)

        # integrate [t1, thS] then [th0, t1]
        for k in range(SUBS-1, -1, -1):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                v, _ = integrate.quad(cdf_f, thetas[k], thetas[k+1], args=args,
                                      epsabs=max(total*tol,abst)/SUBS,
                                      epsrel=tol, limit=1000)
            total += v
    else:
        # max at left, integrate left-to-right
        thetas = [th0, None, thS]
        gvals  = [g0,  None, gS ]
        gstart  = max(g0, 1e-300)
        target  = -np.log(gstart * 1e-2)
        try:
            t1, _ = _brentq(lambda t,*a: aux_f(t,*a)-target, args,
                             th0, thS, 1e-9*(thS-th0))
        except Exception:
            t1 = (th0+thS)*0.5
        thetas[1] = t1
        gvals[1]  = cdf_f(t1, *args)

        for k in range(1, SUBS+1):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                v, _ = integrate.quad(cdf_f, thetas[k-1], thetas[k], args=args,
                                      epsabs=max(total*tol,abst)/SUBS,
                                      epsrel=tol, limit=1000)
            total += v

    return total


# ---------------------------------------------------------------------------
# Point-wise PDF
# ---------------------------------------------------------------------------

def _pdf_point(d, x):
    z = d.zone

    if z == _GAUSS:
        x_ = (x - d.mu_0) / d.sigma
        return 0.5 * np.sqrt(1.0/np.pi) / d.sigma * np.exp(-x_*x_*0.25)

    if z == _CAUCHY:
        x_ = (x - d.mu_0) / d.sigma
        return (1.0/np.pi) / (1.0 + x_*x_) / d.sigma

    if z == _LEVY:
        xxi = (x - d.mu_0) / d.sigma - d.xi
        if xxi > 0.0 and d.beta > 0.0:
            return (np.sqrt(d.sigma * 0.5 / np.pi) *
                    np.exp(-d.sigma*0.5/(xxi*d.sigma)) /
                    (xxi*d.sigma)**1.5)
        elif xxi < 0.0 and d.beta < 0.0:
            axxi = abs(xxi)
            return (np.sqrt(d.sigma * 0.5 / np.pi) *
                    np.exp(-d.sigma*0.5/(axxi*d.sigma)) /
                    (axxi*d.sigma)**1.5)
        return 0.0

    if z == _ALPHA_1:
        x_ = (x - d.mu_0) / d.sigma
        dc = _copy(d)
        if dc.beta < 0.0:
            x_ = -x_
            dc.beta_ = -dc.beta
        else:
            dc.beta_ = dc.beta
        dc.xxipow = -np.pi * x_ * dc.c2_part
        pdf = _integrate_pdf(dc)
        return dc.c2_part * pdf / dc.sigma

    # _STABLE zone
    x_  = (x - d.mu_0) / d.sigma
    xxi = x_ - d.xi

    dc = _copy(d)

    if abs(xxi) <= _XXI_TH:
        pdf = (np.exp(gammaln(1.0 + 1.0/dc.alpha)) *
               np.cos(dc.theta0) / (np.pi * dc.S))
        return pdf / dc.sigma

    if xxi < 0.0:
        xxi = -xxi
        dc.theta0_ = -dc.theta0
        dc.beta_   = -dc.beta
    else:
        dc.theta0_ = dc.theta0
        dc.beta_   = dc.beta

    if abs(dc.theta0_ + np.pi*0.5) < 2*_THETA_TH:
        return 0.0

    dc.xxipow = dc.alphainvalpha1 * np.log(abs(xxi))
    pdf = _integrate_pdf(dc)
    return dc.c2_part / xxi * pdf / dc.sigma


# ---------------------------------------------------------------------------
# Point-wise CDF
# ---------------------------------------------------------------------------

def _cdf_point(d, x):
    z = d.zone

    if z == _GAUSS:
        x_ = (x - d.mu_0) / d.sigma
        return 0.5 + 0.5 * special.erf(x_ * 0.5)

    if z == _CAUCHY:
        x_ = (x - d.mu_0) / d.sigma
        return 0.5 + (1.0/np.pi) * np.arctan(x_)

    if z == _LEVY:
        xxi = (x - d.mu_0) / d.sigma - d.xi
        if xxi > 0.0 and d.beta > 0.0:
            return special.erfc(np.sqrt(0.5 / xxi))
        elif xxi < 0.0 and d.beta < 0.0:
            return special.erfc(np.sqrt(-0.5 / xxi))
        return 0.0

    if z == _ALPHA_1:
        x_ = (x - d.mu_0) / d.sigma
        dc = _copy(d)
        if dc.beta < 0.0:
            x_     = -x_
            dc.beta_ = -dc.beta
        else:
            dc.beta_ = dc.beta
        dc.xxipow = -np.pi * x_ * 0.5 / dc.beta_
        cdf = _integrate_cdf(dc)
        if dc.beta > 0.0:
            return dc.c3 * cdf
        else:
            return 1.0 - dc.c3 * cdf

    # _STABLE zone
    x_  = (x - d.mu_0) / d.sigma
    xxi = x_ - d.xi
    dc  = _copy(d)

    if abs(xxi) < _XXI_TH:
        return (1.0/np.pi) * (np.pi*0.5 - dc.theta0)

    if xxi < 0.0:
        dc.theta0_ = -dc.theta0
        dc.beta_   = -dc.beta
        if abs(dc.theta0_ + np.pi*0.5) < _THETA_TH:
            return 0.0
    else:
        dc.theta0_ = dc.theta0
        dc.beta_   = dc.beta
        if abs(dc.theta0_ + np.pi*0.5) < _THETA_TH:
            return 1.0

    dc.xxipow = dc.alphainvalpha1 * np.log(abs(xxi))
    cdf = _integrate_cdf(dc)

    if xxi > 0.0:
        return dc.c1 + dc.c3 * cdf
    elif dc.alpha > 1.0:
        return -dc.c3 * cdf
    else:
        return 0.5 - (dc.theta0 + cdf) / np.pi


# ---------------------------------------------------------------------------
# Quantile point  (matching stable_q_point in stable_q.c)
# ---------------------------------------------------------------------------

# Precalculated table for quick initial inversion  (from stable_q.c)
_PRECALC = np.array([
[[-1.890857122067030e+06,-1.074884919696010e+03,-9.039223076384694e+01,-2.645987890965098e+01,-1.274134564492298e+01,-7.864009406553024e+00,-5.591791397752695e+00,-4.343949435866958e+00,-3.580521076832391e+00,-3.077683537175253e+00,-2.729262880847457e+00,-2.479627528870857e+00,-2.297138304998905e+00,-2.162196365947914e+00,-2.061462692277420e+00,-1.985261982958637e+00,-1.926542865732525e+00,-1.880296841910385e+00,-1.843044812063057e+00,-1.812387604873646e+00],
 [-1.476366405440763e+05,-2.961237538429159e+02,-3.771873580263473e+01,-1.357404219788403e+01,-7.411052003232824e+00,-4.988799898398770e+00,-3.787942909197120e+00,-3.103035515608863e+00,-2.675942594722292e+00,-2.394177022026705e+00,-2.202290611202918e+00,-2.070075681428623e+00,-1.979193969170630e+00,-1.917168989568703e+00,-1.875099179801364e+00,-1.846852935880107e+00,-1.828439745755405e+00,-1.817388844989596e+00,-1.812268962543248e+00,-1.812387604873646e+00],
 [-4.686998894118387e+03,-5.145071882481552e+01,-1.151718246460839e+01,-5.524535336243413e+00,-3.611648531595958e+00,-2.762379160216148e+00,-2.313577186902494e+00,-2.052416861482463e+00,-1.893403771865641e+00,-1.796585983161395e+00,-1.740583121589162e+00,-1.711775396141753e+00,-1.700465158047576e+00,-1.700212465596452e+00,-1.707238269631509e+00,-1.719534615317151e+00,-1.736176665562027e+00,-1.756931455967477e+00,-1.782079727531726e+00,-1.812387604873646e+00],
 [-2.104710824345458e+01,-3.379418096823576e+00,-1.919928049616870e+00,-1.508399002681057e+00,-1.348510542803496e+00,-1.284465355994317e+00,-1.267907903071982e+00,-1.279742001004255e+00,-1.309886183701422e+00,-1.349392554642457e+00,-1.391753942957071e+00,-1.434304119387730e+00,-1.476453646904256e+00,-1.518446568503842e+00,-1.560864595722380e+00,-1.604464355709833e+00,-1.650152416312346e+00,-1.699029550621646e+00,-1.752489822658308e+00,-1.812387604873646e+00],
 [-1.267075422596289e-01,-2.597188113311268e-01,-4.004811495862077e-01,-5.385024279816432e-01,-6.642916520777534e-01,-7.754208907962602e-01,-8.732998811318613e-01,-9.604322013853581e-01,-1.039287445657237e+00,-1.111986321525904e+00,-1.180285915835185e+00,-1.245653509438976e+00,-1.309356535558631e+00,-1.372547245869795e+00,-1.436342854982504e+00,-1.501904088536648e+00,-1.570525854475943e+00,-1.643747672313277e+00,-1.723509779436442e+00,-1.812387604873646e+00],
 [-1.582153175255304e-01,-3.110425775503970e-01,-4.383733961816599e-01,-5.421475800719634e-01,-6.303884905318050e-01,-7.089178961038225e-01,-7.814055112235458e-01,-8.502117698317242e-01,-9.169548634355569e-01,-9.828374636178471e-01,-1.048835660976022e+00,-1.115815771583362e+00,-1.184614345408666e+00,-1.256100352867799e+00,-1.331235978799527e+00,-1.411143947581252e+00,-1.497190629447853e+00,-1.591104422133556e+00,-1.695147748117837e+00,-1.812387604873646e+00]],
[[-4.738866777987500e+02,-1.684460387562537e+01,-5.619926961081743e+00,-3.281734135829228e+00,-2.397479160864619e+00,-1.959508008521143e+00,-1.708174380583835e+00,-1.550822278332538e+00,-1.447013328833974e+00,-1.376381920471173e+00,-1.327391983207241e+00,-1.292811209009340e+00,-1.267812588403031e+00,-1.249132310044230e+00,-1.234616432819130e+00,-1.222879780072203e+00,-1.213041554808853e+00,-1.204541064608597e+00,-1.197016952370690e+00,-1.190232162899989e+00],
 [-2.185953347160669e+01,-3.543320127025984e+00,-1.977029667649595e+00,-1.507632281031653e+00,-1.303310228044346e+00,-1.199548019673933e+00,-1.144166826374866e+00,-1.115692821970145e+00,-1.103448361903579e+00,-1.101126400280696e+00,-1.104531584444055e+00,-1.110930462397609e+00,-1.118760810700929e+00,-1.127268239360369e+00,-1.136171639806347e+00,-1.145449097190615e+00,-1.155224344271089e+00,-1.165719407748303e+00,-1.177246763148178e+00,-1.190232162899989e+00],
 [-2.681009914911080e-01,-4.350930213152404e-01,-5.305212880041126e-01,-6.015232065896753e-01,-6.620641788021128e-01,-7.174026993828067e-01,-7.694003004766365e-01,-8.178267862332173e-01,-8.615585464741182e-01,-9.003104216523169e-01,-9.347554970493899e-01,-9.658656088352816e-01,-9.945788535033495e-01,-1.021718797792234e+00,-1.048005562158225e+00,-1.074094694885961e+00,-1.100624477495892e+00,-1.128270402039747e+00,-1.157812818875688e+00,-1.190232162899989e+00],
 [-9.503065419472154e-02,-1.947070824738389e-01,-2.987136341021804e-01,-3.973064532664002e-01,-4.838698271554803e-01,-5.579448431371428e-01,-6.215822273361273e-01,-6.771753949313707e-01,-7.267793058476849e-01,-7.720164852674839e-01,-8.141486817740096e-01,-8.541760575495752e-01,-8.929234555236560e-01,-9.311104141820112e-01,-9.694099704722252e-01,-1.008502023575024e+00,-1.049129636922346e+00,-1.092166845038550e+00,-1.138712425453996e+00,-1.190232162899989e+00],
 [-1.264483719244014e-01,-2.437377726529247e-01,-3.333750988387906e-01,-4.016893641684894e-01,-4.577316520822721e-01,-5.069548741156986e-01,-5.523620701546919e-01,-5.956554729327528e-01,-6.378655338388568e-01,-6.796745661620428e-01,-7.215886443544494e-01,-7.640354693071291e-01,-8.074261467088205e-01,-8.522003643607233e-01,-8.988670244927734e-01,-9.480479125009214e-01,-1.000533792677121e+00,-1.057363229272293e+00,-1.119941850176443e+00,-1.190232162899989e+00],
 [-1.526287733702501e-01,-2.498255243669921e-01,-3.063859169446500e-01,-3.504924054764082e-01,-3.911254396222550e-01,-4.309657384679277e-01,-4.709130419301468e-01,-5.113624096299824e-01,-5.525816075847192e-01,-5.948321009341774e-01,-6.384119892912432e-01,-6.836776839822375e-01,-7.310612144698296e-01,-7.810921001396979e-01,-8.344269070778757e-01,-8.918931068397437e-01,-9.545526172382969e-01,-1.023797332562095e+00,-1.101496412960141e+00,-1.190232162899989e+00]],
[[-1.354883142615948e+00,-8.855778500552980e-01,-7.773858277863260e-01,-7.357727812399337e-01,-7.181850957003714e-01,-7.120493514301658e-01,-7.121454153857569e-01,-7.157018373526386e-01,-7.209253714350538e-01,-7.265425280053609e-01,-7.317075569303094e-01,-7.359762286696208e-01,-7.392122467978279e-01,-7.414607677550720e-01,-7.428480570989012e-01,-7.435216571211187e-01,-7.436225251216279e-01,-7.432733099840527e-01,-7.425762029730668e-01,-7.416143171871161e-01],
 [-5.193811327974376e-02,-1.633949875159595e-01,-2.617724006156590e-01,-3.392619822712012e-01,-4.018554923458003e-01,-4.539746445467862e-01,-4.979328472153985e-01,-5.348184073267473e-01,-5.654705188376931e-01,-5.909430146259388e-01,-6.123665499489599e-01,-6.307488506465194e-01,-6.469130897780404e-01,-6.615145568123281e-01,-6.750798357120451e-01,-6.880470899358724e-01,-7.008026232247697e-01,-7.137148222421971e-01,-7.271697520465581e-01,-7.416143171871161e-01],
 [-6.335376612981386e-02,-1.297738965263227e-01,-1.985319371835911e-01,-2.624863717000360e-01,-3.174865471926985e-01,-3.637544360366539e-01,-4.030045272659678e-01,-4.369896090801292e-01,-4.671253359013797e-01,-4.944847533335236e-01,-5.198770070249209e-01,-5.439265161390062e-01,-5.671356857543234e-01,-5.899325077218274e-01,-6.127077038151078e-01,-6.358474023877762e-01,-6.597648782206755e-01,-6.849381555866478e-01,-7.119602076523737e-01,-7.416143171871161e-01],
 [-9.460338726038994e-02,-1.756165596280472e-01,-2.282691311262980e-01,-2.638458905915733e-01,-2.918110046315503e-01,-3.167744873288179e-01,-3.408290016876749e-01,-3.649204420006245e-01,-3.894754728525021e-01,-4.146904022890949e-01,-4.406707089221509e-01,-4.675033009839270e-01,-4.952960990683358e-01,-5.242037261193876e-01,-5.544463409264927e-01,-5.863313160876512e-01,-6.202819599064874e-01,-6.568811178840162e-01,-6.969403639254603e-01,-7.416143171871159e-01],
 [-1.158003423724520e-01,-1.620942232133271e-01,-1.790483132028017e-01,-1.937097725890709e-01,-2.109729530977958e-01,-2.311198638992638e-01,-2.537077422985343e-01,-2.783252370301364e-01,-3.047045003309861e-01,-3.327092628454751e-01,-3.623063449447594e-01,-3.935470145089454e-01,-4.265595391976379e-01,-4.615525703717921e-01,-4.988293297210071e-01,-5.388134824040952e-01,-5.820906647738434e-01,-6.294732446564461e-01,-6.821024214831549e-01,-7.416143171871159e-01],
 [-5.695213481951577e-02,-2.485009114767256e-02,-2.455774348005581e-02,-4.243720620421176e-02,-6.906960852184874e-02,-1.000745485866474e-01,-1.334091111747126e-01,-1.681287272131953e-01,-2.038409527302062e-01,-2.404547731975402e-01,-2.780623638274261e-01,-3.168837529800063e-01,-3.572466721186688e-01,-3.995862986780706e-01,-4.444626893956575e-01,-4.925935308416445e-01,-5.449092276644302e-01,-6.026377433551201e-01,-6.674379829825384e-01,-7.416143171871159e-01]],
[[-4.719005698760254e-03,-5.039419714218448e-02,-1.108600074872916e-01,-1.646393852283324e-01,-2.088895889525075e-01,-2.445873831127209e-01,-2.729819770922066e-01,-2.951510874462016e-01,-3.121233685073350e-01,-3.249196962329062e-01,-3.344714240325961e-01,-3.415532212363377e-01,-3.467713617249639e-01,-3.505859000173167e-01,-3.533413466958321e-01,-3.552947623689004e-01,-3.566384591258251e-01,-3.575167387322836e-01,-3.580387843935552e-01,-3.582869092425832e-01],
 [-3.167687806490741e-02,-6.488347295237770e-02,-9.913854730442322e-02,-1.306663969875579e-01,-1.574578108363950e-01,-1.797875581290475e-01,-1.986122400020671e-01,-2.148458045681510e-01,-2.292024720743768e-01,-2.422125650878785e-01,-2.542699931601989e-01,-2.656748454748664e-01,-2.766656461455947e-01,-2.874428940341864e-01,-2.981872822548070e-01,-3.090746307371333e-01,-3.202900038682522e-01,-3.320450798333745e-01,-3.445973947956370e-01,-3.582869092425832e-01],
 [-6.256908981229170e-02,-1.058190431028687e-01,-1.215669874255146e-01,-1.261149689648148e-01,-1.284283108027729e-01,-1.318108373643454e-01,-1.372885008966837e-01,-1.450218673440198e-01,-1.548461140242879e-01,-1.664940537646226e-01,-1.796994139325742e-01,-1.942454974557965e-01,-2.099854734361004e-01,-2.268483937252861e-01,-2.448403779828917e-01,-2.640470286750166e-01,-2.846415660837839e-01,-3.069024734642628e-01,-3.312464672828315e-01,-3.582869092425832e-01],
 [-7.132464704948761e-02,-5.885471032381771e-02,-3.846810486653290e-02,-2.801768649688129e-02,-2.615407079824540e-02,-3.037902421859952e-02,-3.894619676380785e-02,-5.076849313651704e-02,-6.518223105549245e-02,-8.178056142331483e-02,-1.003134231215546e-01,-1.206343411798188e-01,-1.426762955132322e-01,-1.664453845103147e-01,-1.920257997377931e-01,-2.195942670864279e-01,-2.494428999135824e-01,-2.820166786810741e-01,-3.179740384308457e-01,-3.582869092425832e-01],
 [ 1.186775035989228e-01, 1.847231744541209e-01, 1.899666578065291e-01, 1.756596652192159e-01, 1.538218851318199e-01, 1.287679439328719e-01, 1.022243387982872e-01, 7.488543991005173e-02, 4.698265181928261e-02, 1.852002327642577e-02,-1.062008675791458e-02,-4.062891141128176e-02,-7.175196683590498e-02,-1.042870733773311e-01,-1.385948877988075e-01,-1.751227987938045e-01,-2.144432379167035e-01,-2.573138196343415e-01,-3.047716553689650e-01,-3.582869092425832e-01],
 [ 1.359937191266603e+00, 7.928324704017256e-01, 6.068350758065271e-01, 4.949176895753282e-01, 4.117787224185477e-01, 3.435869264264112e-01, 2.844376471729288e-01, 2.312306852681522e-01, 1.820841981890349e-01, 1.357181057787019e-01, 9.117291945474759e-02, 4.766184332000264e-02, 4.481886485253039e-03,-3.904933750228177e-02,-8.364689014849616e-02,-1.301133939768983e-01,-1.794049920724848e-01,-2.327202766583559e-01,-2.916310469293936e-01,-3.582869092425832e-01]],
[[ 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00, 0.000000000000000e+00],
 [-2.998229841415443e-02,-3.235136568035350e-02,-1.058934315424071e-02, 1.472786013654386e-02, 3.649529125352272e-02, 5.320761222262883e-02, 6.497369053185199e-02, 7.235439352353751e-02, 7.603800885095309e-02, 7.671459793802816e-02, 7.500001602159387e-02, 7.139599669434762e-02, 6.628276247821394e-02, 5.992932695316782e-02, 5.250925428603021e-02, 4.411421669339249e-02, 3.476266163507976e-02, 2.439917920106283e-02, 1.289010976694223e-02, 0.000000000000000e+00],
 [-4.911181618214269e-04, 7.928758678692660e-02, 1.295711243349632e-01, 1.575625247967377e-01, 1.726794061650541e-01, 1.799982238321182e-01, 1.821699713013862e-01, 1.806145618464317e-01, 1.761248753943454e-01, 1.691770293512301e-01, 1.600901411017374e-01, 1.491003610537801e-01, 1.363865273697878e-01, 1.220722641614886e-01, 1.062191001109524e-01, 8.881586460416716e-02, 6.976629777350905e-02, 4.886974404989612e-02, 2.578932638717129e-02, 0.000000000000000e+00],
 [ 6.444732609572413e-01, 5.412205715497974e-01, 4.864603927210872e-01, 4.457073928551408e-01, 4.118964225372133e-01, 3.823074983529713e-01, 3.554905959697276e-01, 3.305043126978712e-01, 3.066571802106021e-01, 2.834017043112906e-01, 2.602853501366307e-01, 2.369238065872132e-01, 2.129824521942899e-01, 1.881563959610275e-01, 1.621474808586950e-01, 1.346349888095220e-01, 1.052403813710735e-01, 7.348119932151805e-02, 3.870673240105876e-02, 0.000000000000000e+00],
 [ 4.884639795042095e+00, 1.686842470765597e+00, 1.132342494635284e+00, 8.944978064032267e-01, 7.538011200000044e-01, 6.558265419066330e-01, 5.806408912949470e-01, 5.191065509143589e-01, 4.663489244354866e-01, 4.194539705064985e-01, 3.765099860312678e-01, 3.361566147323812e-01, 2.973499640484341e-01, 2.592283952427927e-01, 2.210255604589869e-01, 1.820030836908522e-01, 1.413881485626739e-01, 9.829989964989198e-02, 5.165115573609639e-02, 0.000000000000000e+00],
 [ 2.410567057697245e+01, 4.005534670805399e+00, 2.144263118197206e+00, 1.518214626927320e+00, 1.198109338317733e+00, 9.966378800612080e-01, 8.532685386168033e-01, 7.427048697651345e-01, 6.524693172360032e-01, 5.756299950589361e-01, 5.079606300067100e-01, 4.466711396792393e-01, 3.897746494263863e-01, 3.357416130711989e-01, 2.832892169418335e-01, 2.312355801087936e-01, 1.783807793433976e-01, 1.233869208812706e-01, 6.463145748462040e-02, 9.714451465470120e-17]],
[[ 4.719005698760275e-03, 5.039419714218456e-02, 1.108600074872919e-01, 1.646393852283322e-01, 2.088895889525074e-01, 2.445873831127209e-01, 2.729819770922065e-01, 2.951510874462016e-01, 3.121233685073347e-01, 3.249196962329060e-01, 3.344714240325963e-01, 3.415532212363379e-01, 3.467713617249641e-01, 3.505859000173170e-01, 3.533413466958320e-01, 3.552947623689000e-01, 3.566384591258254e-01, 3.575167387322835e-01, 3.580387843935554e-01, 3.582869092425831e-01],
 [ 1.944613194060750e-01, 3.117984496788369e-01, 3.615078716560812e-01, 3.879646155737581e-01, 4.042606354602197e-01, 4.152379986226543e-01, 4.229018705591941e-01, 4.280900470005300e-01, 4.311273812611276e-01, 4.321442286112657e-01, 4.312423594533669e-01, 4.285591238013830e-01, 4.242644840754073e-01, 4.185310514289916e-01, 4.115050794489342e-01, 4.032875933324668e-01, 3.939222836649399e-01, 3.833860261287606e-01, 3.715758694363207e-01, 3.582869092425831e-01],
 [ 3.045958300133999e+00, 1.315675725057089e+00, 9.757973307352019e-01, 8.294361410388060e-01, 7.456405896421689e-01, 6.900226415397631e-01, 6.495436520935480e-01, 6.180526887451320e-01, 5.921654464012007e-01, 5.697923159645174e-01, 5.495326577846258e-01, 5.304020801294532e-01, 5.116943409858906e-01, 4.928954730588648e-01, 4.736165965702772e-01, 4.535361612745278e-01, 4.323485980953122e-01, 4.097162006469898e-01, 3.852184728042033e-01, 3.582869092425835e-01],
 [ 2.339312510820383e+01, 3.858569195402605e+00, 2.091507439545032e+00, 1.515362821077606e+00, 1.231804842218289e+00, 1.060749495885882e+00, 9.442937075476816e-01, 8.583603822642385e-01, 7.911221543980916e-01, 7.360251815557063e-01, 6.890778676134198e-01, 6.476526200515113e-01, 6.099033923678876e-01, 5.744600864566568e-01, 5.402514096915735e-01, 5.063904595668142e-01, 4.720865286037160e-01, 4.365637761840112e-01, 3.989743423180101e-01, 3.582869092425835e-01],
 [ 1.231812404655975e+02, 9.151933726881031e+00, 3.856468345925451e+00, 2.470027172456050e+00, 1.862167039303084e+00, 1.521067254392224e+00, 1.300039377551776e+00, 1.142711537858461e+00, 1.023045102736937e+00, 9.273664178094935e-01, 8.477633920324498e-01, 7.792812067953944e-01, 7.185943530039393e-01, 6.633207377171386e-01, 6.116407715135426e-01, 5.620594176198462e-01, 5.132627179036522e-01, 4.639774715385669e-01, 4.128508865888630e-01, 3.582869092425835e-01],
 [ 5.049829135345403e+02, 1.890722475322573e+01, 6.427275565975617e+00, 3.715903402980179e+00, 2.636417882085815e+00, 2.065989355542487e+00, 1.711228437455139e+00, 1.466088158475343e+00, 1.283765226486882e+00, 1.140575450959062e+00, 1.023262411940948e+00, 9.237922892835746e-01, 8.369566524681974e-01, 7.591595457820643e-01, 6.877508180861301e-01, 6.206265009880273e-01, 5.559603894356728e-01, 4.919976875425384e-01, 4.268552022160075e-01, 3.582869092425835e-01]],
[[ 1.354883142615939e+00, 8.855778500552969e-01, 7.773858277863266e-01, 7.357727812399328e-01, 7.181850957003700e-01, 7.120493514301658e-01, 7.121454153857567e-01, 7.157018373526381e-01, 7.209253714350531e-01, 7.265425280053608e-01, 7.317075569303093e-01, 7.359762286696208e-01, 7.392122467978273e-01, 7.414607677550722e-01, 7.428480570989009e-01, 7.435216571211178e-01, 7.436225251216276e-01, 7.432733099840527e-01, 7.425762029730666e-01, 7.416143171871158e-01],
 [ 2.264297017396562e+01, 3.703766301758638e+00, 2.034998948698223e+00, 1.510923485095245e+00, 1.265729978744353e+00, 1.126910935459891e+00, 1.039315711942880e+00, 9.801156996469297e-01, 9.380990288559633e-01, 9.070002633955093e-01, 8.829463516299942e-01, 8.633779161543368e-01, 8.465599716104961e-01, 8.313215935120923e-01, 8.168794983145117e-01, 8.027015701907034e-01, 7.884022863227798e-01, 7.736657968963813e-01, 7.581862145381915e-01, 7.416143171871158e-01],
 [ 1.955956459466261e+02, 1.118917023817671e+01, 4.357570503031440e+00, 2.718083521990130e+00, 2.041945502327640e+00, 1.682687096145072e+00, 1.462088170281394e+00, 1.313508264506275e+00, 1.206803763884095e+00, 1.126395471042167e+00, 1.063360967480519e+00, 1.012144436660489e+00, 9.690437805764626e-01, 9.314651792280744e-01, 8.975270882378618e-01, 8.658237613571567e-01, 8.352619776464638e-01, 8.049334692839692e-01, 7.740056420537431e-01, 7.416143171871158e-01],
 [ 1.131527106972301e+03, 2.742019413138009e+01, 8.094356141096943e+00, 4.405625422851678e+00, 3.045873292912599e+00, 2.368493556832589e+00, 1.968378518204384e+00, 1.704951233806636e+00, 1.518043793772535e+00, 1.377948007790416e+00, 1.268363069256580e+00, 1.179563109954373e+00, 1.105319244270462e+00, 1.041384485194864e+00, 9.846979577532636e-01, 9.329399521299938e-01, 8.842632875709708e-01, 8.371061471443788e-01, 7.900396709438159e-01, 7.416143171871157e-01],
 [ 4.991370610374878e+03, 5.832596523112534e+01, 1.361736440227531e+01, 6.617793943005997e+00, 4.277065691957527e+00, 3.176211386678905e+00, 2.549432728119129e+00, 2.146593646702069e+00, 1.865193645178458e+00, 1.656315874739094e+00, 1.493891969504980e+00, 1.362797559741365e+00, 1.253624580847262e+00, 1.160149469096889e+00, 1.078008118654219e+00, 1.003953952010710e+00, 9.354146255148074e-01, 8.702022492276336e-01, 8.062927602676150e-01, 7.416143171871157e-01],
 [ 1.808482789458792e+04, 1.120299053944505e+02, 2.131886896428897e+01, 9.395528700779570e+00, 5.735282952993835e+00, 4.099439855675913e+00, 3.198582996879541e+00, 2.632582798272859e+00, 2.243339709179312e+00, 1.957469852365064e+00, 1.736744887299007e+00, 1.559416515511960e+00, 1.412280239489399e+00, 1.286729855523644e+00, 1.176933895080190e+00, 1.078670034479511e+00, 9.886802003678273e-01, 9.042295460529033e-01, 8.227686378257326e-01, 7.416143171871157e-01]],
[[ 4.738866777987514e+02, 1.684460387562540e+01, 5.619926961081758e+00, 3.281734135829232e+00, 2.397479160864624e+00, 1.959508008521145e+00, 1.708174380583837e+00, 1.550822278332539e+00, 1.447013328833976e+00, 1.376381920471174e+00, 1.327391983207241e+00, 1.292811209009341e+00, 1.267812588403031e+00, 1.249132310044230e+00, 1.234616432819130e+00, 1.222879780072204e+00, 1.213041554808854e+00, 1.204541064608597e+00, 1.197016952370690e+00, 1.190232162899990e+00],
 [ 4.841681688643794e+03, 5.491635522391771e+01, 1.256979234254407e+01, 6.069209132601843e+00, 3.940274296039883e+00, 2.963447020215305e+00, 2.423693540860402e+00, 2.089182215079736e+00, 1.865572849084425e+00, 1.708118159360888e+00, 1.593041126030172e+00, 1.506471132927683e+00, 1.439628954887186e+00, 1.386580264484466e+00, 1.343153406231364e+00, 1.306371038922589e+00, 1.274091491606534e+00, 1.244744203398707e+00, 1.217124809801410e+00, 1.190232162899990e+00],
 [ 3.154616792561625e+04, 1.420805372229245e+02, 2.403953052063284e+01, 9.998426062380954e+00, 5.930362539243756e+00, 4.190132768594454e+00, 3.268280841745006e+00, 2.710662024401290e+00, 2.341995909523891e+00, 2.082469140437107e+00, 1.891158929781140e+00, 1.745070641877115e+00, 1.630251730907927e+00, 1.537630629971792e+00, 1.460938380853296e+00, 1.395630981221581e+00, 1.338301797693731e+00, 1.286320343916442e+00, 1.237570697847646e+00, 1.190232162899990e+00],
 [ 1.520631636586534e+05, 3.148956061770992e+02, 4.132943146104890e+01, 1.518515134801384e+01, 8.367182529059960e+00, 5.624308785058203e+00, 4.226708866462347e+00, 3.402197103627229e+00, 2.865360079281767e+00, 2.490393899977397e+00, 2.214464603850502e+00, 2.003098342270666e+00, 1.835905829230373e+00, 1.700021765831942e+00, 1.586823477367793e+00, 1.490188322141933e+00, 1.405530485165501e+00, 1.329245194088195e+00, 1.258353899045780e+00, 1.190232162899990e+00],
 [ 5.901656732159231e+05, 6.246491282963873e+02, 6.581680474603525e+01, 2.173557079848703e+01, 1.125045444319795e+01, 7.254212029229660e+00, 5.287806421003054e+00, 4.154585933912857e+00, 3.428194997160839e+00, 2.925780747207696e+00, 2.557944985263177e+00, 2.276562749626175e+00, 2.053593165082403e+00, 1.871725504345519e+00, 1.719630879614922e+00, 1.589489775546923e+00, 1.475587597649461e+00, 1.373481210080780e+00, 1.279472666002594e+00, 1.190232162899990e+00],
 [ 1.944624278667431e+06, 1.139848804168331e+03, 9.894809619823921e+01, 2.974824391888133e+01, 1.458002371721213e+01, 9.070365685373144e+00, 6.442950257298201e+00, 4.960971490178073e+00, 4.025088868546689e+00, 3.384287797654701e+00, 2.918103805585008e+00, 2.562588803694463e+00, 2.281050180010934e+00, 2.051085944176459e+00, 1.858294826115218e+00, 1.692973560150181e+00, 1.548256386823049e+00, 1.418980226656540e+00, 1.300924242481222e+00, 1.190232162899990e+00]],
[[ 1.890857122067037e+06, 1.074884919696010e+03, 9.039223076384690e+01, 2.645987890965103e+01, 1.274134564492299e+01, 7.864009406553027e+00, 5.591791397752693e+00, 4.343949435866960e+00, 3.580521076832391e+00, 3.077683537175252e+00, 2.729262880847459e+00, 2.479627528870858e+00, 2.297138304998906e+00, 2.162196365947915e+00, 2.061462692277420e+00, 1.985261982958638e+00, 1.926542865732524e+00, 1.880296841910385e+00, 1.843044812063057e+00, 1.812387604873647e+00],
 [ 1.434546473316804e+07, 2.987011338973518e+03, 1.804473474220022e+02, 4.487048929338575e+01, 1.960113433547389e+01, 1.132727408868559e+01, 7.671280872680232e+00, 5.732691330034323e+00, 4.573075545294608e+00, 3.818589092027862e+00, 3.297130126832188e+00, 2.920640582387343e+00, 2.640274592919582e+00, 2.426998377788287e+00, 2.262233765245289e+00, 2.133064562958712e+00, 2.029912595114798e+00, 1.945516531961286e+00, 1.874392545595589e+00, 1.812387604873647e+00],
 [ 7.716266115204613e+07, 6.969521346220721e+03, 3.196657990381036e+02, 6.941784107578007e+01, 2.798990029407097e+01, 1.533578393202605e+01, 9.991349773961725e+00, 7.243609507849516e+00, 5.634462725204553e+00, 4.601857009791827e+00, 3.893417077901593e+00, 3.382471282597797e+00, 2.999860062957988e+00, 2.705234908082859e+00, 2.473610569743775e+00, 2.288441176274372e+00, 2.137883347336651e+00, 2.012884307837858e+00, 1.906295529437326e+00, 1.812387604873647e+00],
 [ 3.253192550565641e+08, 1.437315176424486e+04, 5.205876769957880e+02, 1.006582035946658e+02, 3.790739646062081e+01, 1.985701175129152e+01, 1.252691966593449e+01, 8.859346059355138e+00, 6.752431092162364e+00, 5.418366793527828e+00, 4.510891038980249e+00, 3.859051363710381e+00, 3.370702720510665e+00, 2.992693808833481e+00, 2.692636527934335e+00, 2.449737610939970e+00, 2.249772716121334e+00, 2.082221357100924e+00, 1.938735806854783e+00, 1.812387604873647e+00],
 [ 1.143638705833100e+09, 2.703823367877713e+04, 7.964291266167922e+02, 1.391051003571698e+02, 4.935349274736288e+01, 2.486500490402286e+01, 1.525895955988075e+01, 1.056731639206889e+01, 7.918478700695184e+00, 6.262067266019560e+00, 5.144949915764652e+00, 4.346635348399592e+00, 3.749599176843221e+00, 3.286641675099088e+00, 2.917178603817272e+00, 2.615585030563546e+00, 2.364937633815368e+00, 2.153342270485199e+00, 1.971693892149562e+00, 1.812387604873647e+00],
 [ 3.492208269966229e+09, 4.737075925045248e+04, 1.161019167208514e+03, 1.852377745522907e+02, 6.232811767701676e+01, 3.033836510475647e+01, 1.817240938152932e+01, 1.235792736188858e+01, 9.126360342186048e+00, 7.128676006881803e+00, 5.792462636377325e+00, 4.842756648977701e+00, 4.134472567050430e+00, 3.585273662390985e+00, 3.145733197974777e+00, 2.784907129216124e+00, 2.482804054400846e+00, 2.226062706102394e+00, 2.005149380181030e+00, 1.812387604873647e+00]]
])  # shape (9, 6, 20)  -> precalc[iq][ib][ia]


def _quick_inv(d, q):
    """Trilinear interpolation for initial quantile estimate (stable_quick_inv_point)."""
    alpha = max(d.alpha, 0.1)
    beta  = d.beta
    q_    = q
    sign_b = 1.0

    if beta < 0:
        sign_b = -1.0
        q_ = 1.0 - q_
        beta = -beta

    if beta == 1.0 and q_ < 0.1:
        q_ = 0.1

    if q_ > 0.9 or q_ < 0.1:
        if alpha != 1.0:
            C = (1-alpha) / (np.exp(gammaln(2-alpha)) * np.cos(np.pi*alpha*0.5))
        else:
            C = 2.0 / np.pi
        if q_ > 0.9:
            x0 = ((1-q_) / (C * 0.5 * (1.0+beta))) ** (-1.0/alpha)
        else:
            x0 = -((q_) / (C * 0.5 * (1.0-beta))) ** (-1.0/alpha)
    else:
        ia = int(alpha / 0.1) - 1
        ib = int(beta  / 0.2)
        iq = int(q_    / 0.1) - 1
        xa = (alpha/0.1) % 1.0
        xb = (beta /0.2) % 1.0
        xq = (q_   /0.1) % 1.0

        if alpha == 2.0: ia = 18; xa = 1.0
        if beta  == 1.0: ib = 4;  xb = 1.0
        if q_    == 0.9: iq = 7;  xq = 1.0

        ia = max(0, min(ia, 18))
        ib = max(0, min(ib, 4))
        iq = max(0, min(iq, 7))

        p = np.array([
            _PRECALC[iq  ][ib  ][ia  ], _PRECALC[iq  ][ib  ][ia+1],
            _PRECALC[iq  ][ib+1][ia  ], _PRECALC[iq  ][ib+1][ia+1],
            _PRECALC[iq+1][ib  ][ia  ], _PRECALC[iq+1][ib  ][ia+1],
            _PRECALC[iq+1][ib+1][ia  ], _PRECALC[iq+1][ib+1][ia+1],
        ])
        x0 = (((p[0]*(1-xa)+p[1]*xa)*(1-xb)+(p[2]*(1-xa)+p[3]*xa)*xb)*(1-xq) +
              ((p[4]*(1-xa)+p[5]*xa)*(1-xb)+(p[6]*(1-xa)+p[7]*xa)*xb)*xq)

    return x0 * sign_b * d.sigma + d.mu_0


def _q_point(d, q):
    """Compute the quantile (inverse CDF) at probability q."""
    if d.zone == _GAUSS:
        return stats.norm.ppf(q) * np.sqrt(2) * d.sigma + d.mu_0
    if d.zone == _CAUCHY:
        return np.tan(np.pi*(q - 0.5)) * d.sigma + d.mu_0
    if d.zone == _LEVY:
        return (d.beta * stats.norm.ppf(q/2.0)**(-2.0) + d.xi) * d.sigma + d.mu_0

    x = _quick_inv(d, q)

    if _INV_MAXITER > 0:
        try:
            def f(xv): return _cdf_point(d, xv) - q
            # secant-like iteration (matches gsl_root_fdfsolver_secant)
            INVrelTOL = 1e-6
            x0 = x
            for _ in range(_INV_MAXITER):
                fx  = f(x)
                dfx = _pdf_point(d, x)
                if dfx == 0.0:
                    break
                x1 = x - fx / dfx
                if abs(x1 - x) <= INVrelTOL * max(abs(x), abs(x1)):
                    x = x1
                    break
                x = x1
        except Exception:
            pass

    return x


# ---------------------------------------------------------------------------
# Vectorised public functions
# ---------------------------------------------------------------------------

def _validate(pars):
    alpha, beta, sigma, mu = float(pars[0]), float(pars[1]), float(pars[2]), float(pars[3])
    if not (0 < alpha <= 2):    raise ValueError("alpha must be in (0,2]")
    if not (-1 <= beta <= 1):   raise ValueError("beta must be in [-1,1]")
    if sigma <= 0:               raise ValueError("sigma must be positive")
    if not np.isfinite(mu):     raise ValueError("mu must be finite")
    return alpha, beta, sigma, mu


def stable_pdf(x, pars, parametrization=0, tol=1e-12):
    """PDF of alpha-stable distribution. Matches R libstableR stable_pdf()."""
    alpha, beta, sigma, mu = _validate(pars)
    x = np.asarray(x, dtype=float).ravel()
    d = _build(alpha, beta, sigma, mu, int(parametrization), float(tol))

    if _NB_AVAILABLE:
        return _nb_pdf_array(x, d.zone, d.alpha, d.beta, d.sigma, d.mu_0, d.xi,
                             d.theta0, d.alphainvalpha1, d.k1, d.c2_part,
                             d.AUX1, d.AUX2, _GL_NODES_NB, _GL_WEIGHTS_NB)

    if len(x) == 1:
        return np.array([_pdf_point(d, x[0])])

    def _work(xi):
        return _pdf_point(d, xi)

    with ThreadPoolExecutor(max_workers=_N_THREADS) as ex:
        result = list(ex.map(_work, x))
    return np.array(result)


def stable_cdf(x, pars, parametrization=0, tol=1e-12):
    """CDF of alpha-stable distribution. Matches R libstableR stable_cdf()."""
    alpha, beta, sigma, mu = _validate(pars)
    x = np.asarray(x, dtype=float).ravel()
    d = _build(alpha, beta, sigma, mu, int(parametrization), float(tol))

    if _NB_AVAILABLE:
        return _nb_cdf_array(x, d.zone, d.alpha, d.beta, d.sigma, d.mu_0, d.xi,
                             d.theta0, d.alphainvalpha1, d.k1, d.c1, d.c2_part, d.c3,
                             _GL_NODES_NB, _GL_WEIGHTS_NB)

    if len(x) == 1:
        return np.array([_cdf_point(d, x[0])])

    def _work(xi):
        return _cdf_point(d, xi)

    with ThreadPoolExecutor(max_workers=_N_THREADS) as ex:
        result = list(ex.map(_work, x))
    return np.array(result)


def stable_q(p, pars, parametrization=0, tol=1e-12):
    """Quantile function. Matches R libstableR stable_q()."""
    alpha, beta, sigma, mu = _validate(pars)
    p = np.asarray(p, dtype=float).ravel()
    d = _build(alpha, beta, sigma, mu, int(parametrization), float(tol))
    if len(p) == 1:
        return np.array([_q_point(d, p[0])])

    def _work(pi):
        return _q_point(d, pi)

    with ThreadPoolExecutor(max_workers=_N_THREADS) as ex:
        result = list(ex.map(_work, p))
    return np.array(result)


# ---------------------------------------------------------------------------
# Random number generation  (Chambers-Mallows-Stuck 1976, matching stable_rnd.c)
# ---------------------------------------------------------------------------

def stable_rnd(N, pars, parametrization=0, seed=None):
    """
    Generate N stable random samples using the Chambers-Mallows-Stuck method.
    Matches R libstableR stable_rnd() when the same RNG seed is used.
    """
    alpha, beta, sigma, mu = _validate(pars)
    rng = np.random.default_rng(seed)
    d = _build(alpha, beta, sigma, mu, int(parametrization), 1e-12)

    N = int(N)
    V = np.pi * (rng.random(N) - 0.5)          # uniform on (-pi/2, pi/2)
    W = -np.log(rng.random(N))                   # exponential(1)

    if alpha == 2.0:
        rnd = np.sqrt(2.0) * rng.standard_normal(N)

    elif alpha == 1.0 and beta == 0.0:
        rnd = np.tan(V)

    elif alpha == 0.5 and abs(beta) == 1.0:
        sn = rng.standard_normal(N)
        rnd = beta / sn**2

    elif beta == 0.0:
        rnd = (np.sin(alpha*V) / np.cos(V)**(1.0/alpha) *
               (np.cos(V*(1-alpha)) / W)**((1-alpha)/alpha))

    elif alpha != 1.0:
        aux = beta * np.tan(np.pi * 0.5 * alpha)
        B   = np.arctan(aux)
        S   = (1.0 + aux*aux) ** (0.5 / alpha)
        rnd = (S * np.sin(alpha*V + B) / np.cos(V)**(1.0/alpha) *
               (np.cos((1-alpha)*V - B) / W)**((1-alpha)/alpha))

    else:   # alpha == 1, beta != 0
        aux = np.pi*0.5 + beta*V
        rnd = (2.0/np.pi) * (aux * np.tan(V) -
               beta * np.log(np.pi * 0.5 * W * np.cos(V) / aux))

    if alpha != 1.0:
        result = d.sigma * rnd + d.mu_1
    else:
        result = d.sigma * rnd + (2.0/np.pi) * beta * d.sigma * np.log(d.sigma) + d.mu_1

    return result


# ---------------------------------------------------------------------------
# McCulloch (1986) quantile-based initial estimator  (matching mcculloch.c)
# ---------------------------------------------------------------------------

# Tables from mcculloch.c
_ENA = np.array([
    [2.4388,2.4388,2.4388,2.4388,2.4388],[2.5120,2.5117,2.5125,2.5129,2.5148],
    [2.6080,2.6093,2.6101,2.6131,2.6174],[2.7369,2.7376,2.7387,2.7420,2.7464],
    [2.9115,2.9090,2.9037,2.8998,2.9016],[3.1480,3.1363,3.1119,3.0919,3.0888],
    [3.4635,3.4361,3.3778,3.3306,3.3161],[3.8824,3.8337,3.7199,3.6257,3.5997],
    [4.4468,4.3651,4.1713,4.0052,3.9635],[5.2172,5.0840,4.7778,4.5122,4.4506],
    [6.3140,6.0978,5.6241,5.2195,5.1256],[7.9098,7.5900,6.8606,6.2598,6.1239],
    [10.4480,9.9336,8.7790,7.9005,7.6874],[14.8378,13.9540,12.0419,10.7219,10.3704],
    [23.4831,21.7682,18.3320,16.2163,15.5841],[44.2813,40.1367,33.0018,29.1399,27.7822],
])
_ENB = np.array([
    [0.0000,0.0000,0.0000,0.0000,0.0000],[0.0000,0.0179,0.0357,0.0533,0.0710],
    [0.0000,0.0389,0.0765,0.1133,0.1480],[0.0000,0.0626,0.1226,0.1784,0.2281],
    [0.0000,0.0895,0.1736,0.2478,0.3090],[0.0000,0.1183,0.2282,0.3199,0.3895],
    [0.0000,0.1478,0.2849,0.3942,0.4686],[0.0000,0.1769,0.3422,0.4703,0.5458],
    [0.0000,0.2062,0.3993,0.5473,0.6210],[0.0000,0.2362,0.4561,0.6240,0.6934],
    [0.0000,0.2681,0.5134,0.6993,0.7616],[0.0000,0.3026,0.5726,0.7700,0.8248],
    [0.0000,0.3415,0.6343,0.8339,0.8805],[0.0000,0.3865,0.6994,0.8900,0.9269],
    [0.0000,0.4408,0.7678,0.9362,0.9620],[0.0000,0.5095,0.8381,0.9700,0.9847],
])
_ENC = np.array([
    [1.9078,1.9078,1.9078,1.9078,1.9078],[1.9140,1.9150,1.9160,1.9185,1.9210],
    [1.9210,1.9220,1.9275,1.9360,1.9470],[1.9270,1.9305,1.9425,1.9610,1.9870],
    [1.9330,1.9405,1.9620,1.9970,2.0430],[1.9390,1.9520,1.9885,2.0450,2.1160],
    [1.9460,1.9665,2.0220,2.1065,2.2110],[1.9550,1.9845,2.0670,2.1880,2.3330],
    [1.9650,2.0075,2.1255,2.2945,2.4910],[1.9800,2.0405,2.2050,2.4345,2.6965],
    [2.0000,2.0850,2.3115,2.6240,2.9735],[2.0400,2.1490,2.4610,2.8865,3.3565],
    [2.0980,2.2445,2.6765,3.2650,3.9125],[2.1890,2.3920,3.0040,3.8440,4.7755],
    [2.3370,2.6355,3.5425,4.8085,6.2465],[2.5880,3.0735,4.5340,6.6365,9.1440],
])
_ZA = np.array([
    [0.0000,0.0000,0.0000,0.0000,0.0000],[0.0000,-0.0166,-0.0322,-0.0488,-0.0644],
    [0.0000,-0.0302,-0.0615,-0.0917,-0.1229],[0.0000,-0.0434,-0.0878,-0.1321,-0.1785],
    [0.0000,-0.0556,-0.1113,-0.1699,-0.2315],[0.0000,-0.0660,-0.1340,-0.2060,-0.2830],
    [0.0000,-0.0751,-0.1542,-0.2413,-0.3354],[0.0000,-0.0837,-0.1733,-0.2760,-0.3896],
    [0.0000,-0.0904,-0.1919,-0.3103,-0.4467],[0.0000,-0.0955,-0.2080,-0.3465,-0.5080],
    [0.0000,-0.0980,-0.2230,-0.3830,-0.5760],[0.0000,-0.0986,-0.2372,-0.4239,-0.6525],
    [0.0000,-0.0956,-0.2502,-0.4688,-0.7424],[0.0000,-0.0894,-0.2617,-0.5201,-0.8534],
    [0.0000,-0.0779,-0.2718,-0.5807,-0.9966],[0.0000,-0.0610,-0.2790,-0.6590,-1.1980],
])


def _frctl(x, p):
    """Empirical quantile matching R's type 5 (h=Np+1/2). x must be sorted."""
    n = len(x)
    zi = p * n - 0.5
    i = int(np.floor(zi))
    if zi < 0:   return x[0]
    if zi > n-1: return x[-1]
    th = zi - i
    return (1-th)*x[i] + th*x[i+1]


def _czab(alpha, beta, cn, q50):
    """Estimate sigma and mu_0 from alpha,beta, interquartile range and median."""
    sign = 1 if beta > 0 else (-1 if beta < 0 else 0)
    i = int(np.floor((2-alpha)*10 + 1))
    i = max(1, min(i, 15))
    j = int(np.floor(beta/0.25 + 1))
    j = max(1, min(j, 4))
    t = beta/0.25 - j + 1
    s = (2-alpha)/0.1 - i + 1
    c = (_ENC[i-1,j-1]*(1-s)*(1-t) + _ENC[i,j-1]*s*(1-t) +
         _ENC[i-1,j]*t*(1-s)  + _ENC[i,j]*t*s)
    c = cn / c
    zeta = (_ZA[i-1,j-1]*(1-s)*(1-t) + _ZA[i,j-1]*s*(1-t) +
            _ZA[i-1,j]*t*(1-s)   + _ZA[i,j]*t*s)
    zeta = q50 + c * sign * zeta
    return c, zeta


def stable_fit_init(rnd, parametrization=0):
    """
    McCulloch quantile-based parameter estimator.
    Matches R libstableR stable_fit_init().
    Returns pars = [alpha, beta, sigma, mu].
    """
    rnd = np.sort(np.asarray(rnd, dtype=float).ravel())
    n   = len(rnd)
    q05 = _frctl(rnd, 0.05)
    q25 = _frctl(rnd, 0.25)
    q50 = _frctl(rnd, 0.50)
    q75 = _frctl(rnd, 0.75)
    q95 = _frctl(rnd, 0.95)

    d   = q95 - q05
    cn  = q75 - q25
    if cn == 0:
        cn = 1e-10
    an = d / cn

    if an < 2.4388:
        alpha = 1.95; beta = 0.0; c = cn/1.9078; zeta = q50
    else:
        bn = (q05 + q95 - 2*q50) / d
        sign = 1.0 if bn > 0 else (-1.0 if bn < 0 else 0.0)
        bn   = abs(bn)

        ah = np.zeros(5)
        for jj in range(5):
            for i in range(1, 15):
                if an <= _ENA[i, jj]: break
            t = (an - _ENA[i-1, jj]) / (_ENA[i, jj] - _ENA[i-1, jj])
            ah[jj] = 0.5 if t > 1 else 2 - (i-1+t)*0.1

        bh = np.zeros(16)
        for i in range(1, 16):
            for j in range(1, 4):
                if bn <= _ENB[i, j]: break
            t = (bn - _ENB[i, j-1]) / (_ENB[i, j] - _ENB[i, j-1])
            bh[i] = 1.0 if t > 1 else (j-1+t)*0.25
        bh[0] = 2*bh[1] - bh[2]

        for jj in range(1, 5):
            jjj = jj
            i = int(np.floor((2-ah[jj])*10 + 1))
            i = max(1, min(i, 15))
            aa  = 2 - 0.1*(i-1)
            s2  = -(ah[jj] - aa)*10
            b   = (1-s2)*bh[i-1] + s2*bh[i]
            if b < jj/4.0: break
        jj = jjj

        bb = 0.25*(jj-1)
        t1 = (bh[i-1] - bb) / 0.25
        t2 = (bh[i]   - bb) / 0.25
        s1 = -(ah[jj-1] - aa)*10
        dt = t2 - t1; ds = s2 - s1
        s  = (s1 + t1*ds) / (1 - ds*dt)
        t  = t1 + s*dt
        alpha = aa - s*0.1
        if alpha < 0.5: alpha = 0.5
        beta = bb + t*0.25
        if beta > 1.0: beta = 1.0
        beta *= sign

        c = (_ENC[i-1,jj-1]*(1-s)*(1-t) + _ENC[i,jj-1]*s*(1-t) +
             _ENC[i-1,jj]*t*(1-s)      + _ENC[i,jj]*t*s)
        c = cn / c
        zeta = (_ZA[i-1,jj-1]*(1-s)*(1-t) + _ZA[i,jj-1]*s*(1-t) +
                _ZA[i-1,jj]*t*(1-s)       + _ZA[i,jj]*t*s)
        zeta = q50 + c * sign * zeta

    # convert from (alpha,beta,sigma,mu_0-param) to requested parametrization
    d_tmp = _build(alpha, beta, c, zeta, 0, 1e-6)
    if parametrization == 0:
        return np.array([alpha, beta, c, zeta])
    else:
        return np.array([alpha, beta, c, d_tmp.mu_1])


# ---------------------------------------------------------------------------
# Koutrouvelis (1981) characteristic-function estimator
# ---------------------------------------------------------------------------

def _sample_cf(data, t):
    """Empirical characteristic function at scalar t."""
    return np.exp(1j * t * data).mean()


def _sample_cf_batch(data, t_arr):
    """Vectorised empirical CF for array of t values."""
    return np.exp(1j * np.outer(t_arr, data)).mean(axis=1)


# Bilinear-interpolation tables from stable_koutrouvelis.c
_KK_ALPHA = np.array([1.9, 1.5, 1.3, 1.1, 0.9, 0.7, 0.5, 0.3])
_KK_N     = np.array([200, 800, 1600])
_KK_MAT   = np.array([[9,9,9],[11,11,11],[22,16,14],[24,18,15],
                       [28,22,18],[30,24,20],[86,68,56],[134,124,118]], dtype=float)

_KL_ALPHA = np.array([1.9, 1.5, 1.1, 0.9, 0.7, 0.5, 0.3])
_KL_N     = np.array([200, 800, 1600])
_KL_MAT   = np.array([[9,10,11],[12,14,15],[16,18,17],[14,14,14],
                       [24,16,16],[40,38,36],[70,68,66]], dtype=float)


def _kbl_interp(alpha, N, alpha_arr, n_arr, mat):
    """Bilinear interpolation matching C's chooseK / chooseL."""
    a = float(np.clip(alpha, alpha_arr[-1], alpha_arr[0]))
    n = float(np.clip(N, n_arr[0], n_arr[-1]))
    i = 1
    while i < len(alpha_arr)-1 and alpha_arr[i] >= a:
        i += 1
    j = 1
    while j < len(n_arr)-1 and n_arr[j] <= n:
        j += 1
    xi = 1.0 - (a - alpha_arr[i]) / (alpha_arr[i-1] - alpha_arr[i])
    xj = 1.0 - (n_arr[j] - n) / (n_arr[j] - n_arr[j-1])
    val = (xj * (xi*mat[i,j]     + (1-xi)*mat[i-1,j]) +
           (1-xj)*(xi*mat[i,j-1] + (1-xi)*mat[i-1,j-1]))
    return max(1, int(round(val)))


def _choose_K(alpha, N):
    return _kbl_interp(alpha, N, _KK_ALPHA, _KK_N, _KK_MAT)


def _choose_L(alpha, N):
    return _kbl_interp(alpha, N, _KL_ALPHA, _KL_N, _KL_MAT)


def _ecf_root(s):
    """Find first zero crossing of ECF real part (matching C's ecfRoot)."""
    m = np.mean(np.abs(s))
    if m == 0.0:
        return np.pi / 50.0
    t = 0.0
    val = np.cos(t * s).mean()
    for _ in range(10000):
        if abs(val) <= 1e-3:
            break
        t += val / m
        val = np.cos(t * s).mean()
    return max(t, 1e-6)


def _covYY_diag(t, alpha, beta, N):
    """Diagonal of covariance matrix for step-1 WLS (matching setcovYY)."""
    if abs(alpha - 1.0) < 0.05:
        return np.ones(len(t))
    w = np.tan(alpha * np.pi * 0.5)
    ta = np.abs(t) ** alpha
    diag = np.zeros(len(t))
    for j, (tj, tja) in enumerate(zip(t, ta)):
        stj = np.sign(tj)
        A = 2 * tja   # tja + tja - 0
        B = 0.0       # diagonal: tj==tk, so sign(tj-tk)*beta term vanishes
        D = 0.0       # tja + tja - |2tj|^alpha
        D = tja + tja - (2.0 * abs(tj)) ** alpha
        E = 0.0
        # diagonal j==k: tjmtka=0, tjptka=|2tj|^alpha
        E_term = tja * stj * w + tja * stj * w - (2*abs(tj))**alpha * np.sign(2*tj) * w
        E = beta * E_term
        diag[j] = (np.exp(A)*np.cos(B) + np.exp(D)*np.cos(E) - 2.0) / (2.0 * N * tja**2)
    return np.where(diag > 0, diag, 1.0)


def _covZZ_diag(t, alpha, beta, N):
    """Diagonal of covariance matrix for step-2 WLS (matching setcovZZ)."""
    if abs(alpha - 1.0) < 0.05:
        return np.ones(len(t))
    ta = np.abs(t) ** alpha
    diag = np.zeros(len(t))
    for j, (tj, tja) in enumerate(zip(t, ta)):
        stj = np.sign(tj)
        w = np.tan(alpha * np.pi * 0.5)
        B = beta * (-tja*stj*w + tja*stj*w + 0.0)  # j==k: sign(tj-tk)=0 → 0
        E = beta * (tja*stj*w + tja*stj*w - (2*abs(tj))**alpha * np.sign(2*tj)*w)
        F = tja + tja
        G = -0.0             # -(2*tja - 2*tja) = 0 for j==k → tja+tka-tjmtka=2*tja
        H = -(2.0*abs(tj))**alpha  # -(tja+tka-tjptka) with j==k
        # Actually for diagonal j==k:
        # tjmtka = |tj-tk|^alpha = 0 → G = -calpha * 0 = 0 → exp(G)=1
        diag[j] = np.exp(F) * (np.exp(G)*np.cos(B) - np.exp(H)*np.cos(E)) / (2.0 * N)
    return np.where(diag > 0, diag, 1.0)


def stable_fit_koutrouvelis(rnd, pars_init=None, parametrization=0):
    """
    Koutrouvelis (1981) characteristic-function regression estimator.
    Matches R libstableR stable_fit_koutrouvelis().
    """
    rnd = np.asarray(rnd, dtype=float).ravel()
    N   = len(rnd)

    if pars_init is None or len(pars_init) == 0:
        pars_init = stable_fit_init(rnd, parametrization=0)
    else:
        pars_init = np.asarray(pars_init, dtype=float)
        if parametrization == 1:
            d_tmp = _build(pars_init[0], pars_init[1], pars_init[2], pars_init[3], 1, 1e-6)
            pars_init = np.array([d_tmp.alpha, d_tmp.beta, d_tmp.sigma, d_tmp.mu_0])

    alpha = float(pars_init[0]); beta = float(pars_init[1])
    sigma = float(pars_init[2]); mu1  = float(pars_init[3])

    if sigma == 0.0:
        sigma = float(np.std(rnd))

    # Convert to S1 parametrization (mu_1)
    d_tmp = _build(alpha, beta, sigma, mu1, 0, 1e-6)
    mu1   = d_tmp.mu_1

    alpha_best = alpha; beta_best = beta
    sigma_best = sigma; mu1_best  = mu1
    diff_best  = np.inf

    maxiter = 10; xTol = 0.01

    # standardised data (updated in-place across iterations)
    s = (rnd - mu1) / sigma

    K = L = 0
    t1_arr = t2_arr = None

    alpha_old = alpha; mu1_old = mu1

    for it in range(maxiter):
        # --- Step 1: estimate alpha and sigma ---
        if it <= 1:
            K = _choose_K(alpha, N)
            t1_arr = np.arange(1, K+1) * np.pi / 25.0
            w1 = np.log(t1_arr)   # t > 0, so log(|t|) = log(t)

        phi1 = _sample_cf_batch(s, t1_arr)
        y1   = np.log(-2.0 * np.log(np.maximum(np.abs(phi1), 1e-300)))

        if it == 0:   # OLS
            A = np.column_stack([np.ones(K), w1])
            coef, *_ = np.linalg.lstsq(A, y1, rcond=None)
        else:          # WLS: weights = 1 / diag(covYY)
            wts = 1.0 / _covYY_diag(t1_arr, alpha, beta, N)
            A   = np.column_stack([np.ones(K), w1])
            W   = np.diag(wts)
            coef = np.linalg.lstsq(A.T @ W @ A, A.T @ W @ y1, rcond=None)[0]

        c0, c1    = coef
        alpha_new = float(np.clip(c1, 0.0, 2.0))
        sigma_new = (np.exp(c0) / 2.0) ** (1.0 / max(alpha_new, 1e-4))
        sigma    *= sigma_new
        s        /= sigma_new    # rescale in-place (matches C: s[i] /= sigmanew)

        # --- Step 2: estimate beta and mu1 ---
        if it <= 1:
            L = _choose_L(alpha_new, N)
            t0_ecf   = _ecf_root(s)
            step_u   = min(np.pi / 50.0, t0_ecf / max(L, 1))
            t2_arr   = np.arange(1, L+1) * step_u
            w2_arr   = np.sign(t2_arr) * np.abs(t2_arr) ** alpha_new

        phi2 = _sample_cf_batch(s, t2_arr)
        y2   = np.angle(phi2)

        X2 = np.column_stack([t2_arr, w2_arr])
        if it == 0:   # OLS
            coef2, *_ = np.linalg.lstsq(X2, y2, rcond=None)
        else:          # WLS
            wts2 = 1.0 / _covZZ_diag(t2_arr, alpha_new, beta, N)
            W2   = np.diag(wts2)
            coef2 = np.linalg.lstsq(X2.T @ W2 @ X2, X2.T @ W2 @ y2, rcond=None)[0]

        estshift = float(coef2[0])    # mu1 of standardised data
        w2_coef  = float(coef2[1])

        tan_term = np.tan(np.pi * 0.5 * alpha_new)
        if abs(alpha_new - 1.0) < 0.05 or abs(tan_term) < 1e-10 or abs(alpha_new) > 1.98:
            beta_new = 0.0
        else:
            beta_new = float(np.clip(w2_coef / tan_term, -1.0, 1.0))

        mu1    += sigma * estshift
        s      -= estshift   # remove estimated shift (matches C: s[i] -= estshift)

        alpha_new = float(np.clip(alpha_new, 0.0, 2.0))
        beta_new  = float(np.clip(beta_new, -1.0, 1.0))

        diff = (alpha_new - alpha_old)**2 + (mu1 - mu1_old)**2

        if diff < diff_best:
            diff_best  = diff
            alpha_best = alpha_new; beta_best = beta_new
            sigma_best = sigma;     mu1_best  = mu1

        if diff < xTol:
            alpha = alpha_new; beta = beta_new
            break

        alpha_old = alpha; mu1_old = mu1
        alpha = alpha_new; beta = beta_new

    alpha = float(np.clip(alpha_best, 0.0, 2.0))
    beta  = float(np.clip(beta_best, -1.0, 1.0))
    sigma = max(sigma_best, 0.0)
    mu1   = mu1_best

    d_res = _build(alpha, beta, sigma, mu1, 1, 1e-6)
    if parametrization == 0:
        return np.array([alpha, beta, sigma, d_res.mu_0])
    else:
        return np.array([alpha, beta, sigma, mu1])


# ---------------------------------------------------------------------------
# MLE  (matching stable_fit_mle in stable_fit.c)
# ---------------------------------------------------------------------------

def _loglikelihood(pars, data):
    """Negative log-likelihood for MLE optimization."""
    try:
        alpha, beta, sigma, mu = float(pars[0]), float(pars[1]), float(pars[2]), float(pars[3])
        if not (0 < alpha <= 2 and -1 <= beta <= 1 and sigma > 0 and np.isfinite(mu)):
            return 1e30
        d = _build(alpha, beta, sigma, mu, 0, 1e-6)
        if _NB_AVAILABLE:
            pdfs = _nb_pdf_array(data, d.zone, d.alpha, d.beta, d.sigma, d.mu_0, d.xi,
                                 d.theta0, d.alphainvalpha1, d.k1, d.c2_part,
                                 d.AUX1, d.AUX2, _GL_NODES_NB, _GL_WEIGHTS_NB)
        else:
            with ThreadPoolExecutor(max_workers=_N_THREADS) as ex:
                pdfs = np.array(list(ex.map(lambda x: _pdf_point(d, x), data)))
        mask = pdfs > 0
        if not np.any(mask):
            return 1e30
        return -np.sum(np.log(pdfs[mask]))
    except Exception:
        return 1e30


def _mle_inner(data, pars_init, parametrization, fix_alpha_beta=False):
    """Run scipy minimizer for MLE."""
    p0 = np.asarray(pars_init, dtype=float).copy()

    if fix_alpha_beta:
        # 2D version: optimize over (alpha, beta) and reestimate sigma,mu with McCulloch
        rnd_s = np.sort(data)
        cn    = _frctl(rnd_s, 0.75) - _frctl(rnd_s, 0.25)
        q50   = _frctl(rnd_s, 0.50)

        def cost(ab):
            a = np.clip(1/(1+np.exp(-ab[0]))*2, 0.1, 2.0)
            b = np.tanh(ab[1])
            c, z = _czab(a, b, cn, q50)
            return _loglikelihood([a, b, c, z], data)

        ab0 = np.array([np.log(p0[0]/(2-p0[0]+1e-9)),
                        np.arctanh(np.clip(p0[1], -0.999, 0.999))])
        res = optimize.minimize(cost, ab0, method='Nelder-Mead',
                                options={'xatol':1e-5,'fatol':1e-5,'maxiter':5000})
        a = np.clip(1/(1+np.exp(-res.x[0]))*2, 0.1, 2.0)
        b = np.tanh(res.x[1])
        c, z = _czab(a, b, cn, q50)
        return np.array([a, b, c, z])
    else:
        # full 4D MLE
        def cost(pv):
            # use log-sigma, arctanh-beta, tan-based alpha transforms for unconstrained
            a = np.clip(2.0/np.pi * np.arctan(pv[0]) + 1.0, 0.01, 2.0)
            b = np.clip(2.0/np.pi * np.arctan(pv[1]), -1.0, 1.0)
            c = np.exp(pv[2])
            m = pv[3]
            return _loglikelihood([a, b, c, m], data)

        pv0 = np.array([
            np.tan(np.pi*0.5*(p0[0]-1.0)),
            np.tan(np.pi*0.5*np.clip(p0[1],-0.999,0.999)),
            np.log(p0[2]),
            p0[3],
        ])
        res = optimize.minimize(cost, pv0, method='Nelder-Mead',
                                options={'xatol':1e-5,'fatol':1e-5,'maxiter':10000})
        a = np.clip(2.0/np.pi * np.arctan(res.x[0]) + 1.0, 0.01, 2.0)
        b = np.clip(2.0/np.pi * np.arctan(res.x[1]), -1.0, 1.0)
        c = np.exp(res.x[2])
        m = res.x[3]
        return np.array([a, b, c, m])


def stable_fit_mle(rnd, pars_init=None, parametrization=0):
    """Maximum likelihood estimator. Matches R libstableR stable_fit_mle()."""
    rnd = np.asarray(rnd, dtype=float).ravel()
    if pars_init is None or len(pars_init) == 0:
        p0 = stable_fit_init(rnd, parametrization=0)
    else:
        p0 = np.asarray(pars_init, dtype=float)
        if parametrization == 1:
            d_tmp = _build(p0[0],p0[1],p0[2],p0[3], 1, 1e-6)
            p0 = np.array([d_tmp.alpha, d_tmp.beta, d_tmp.sigma, d_tmp.mu_0])

    result = _mle_inner(rnd, p0, 0, fix_alpha_beta=False)

    if parametrization == 1:
        d_res = _build(result[0],result[1],result[2],result[3], 0, 1e-6)
        result[3] = d_res.mu_1
    return result


def stable_fit_mle2d(rnd, pars_init=None, parametrization=0):
    """
    Modified MLE (2D: optimize alpha,beta; sigma,mu from McCulloch).
    Matches R libstableR stable_fit_mle2d().
    """
    rnd = np.asarray(rnd, dtype=float).ravel()
    if pars_init is None or len(pars_init) == 0:
        p0 = stable_fit_init(rnd, parametrization=0)
    else:
        p0 = np.asarray(pars_init, dtype=float)
        if parametrization == 1:
            d_tmp = _build(p0[0],p0[1],p0[2],p0[3], 1, 1e-6)
            p0 = np.array([d_tmp.alpha, d_tmp.beta, d_tmp.sigma, d_tmp.mu_0])

    result = _mle_inner(rnd, p0, 0, fix_alpha_beta=True)

    if parametrization == 1:
        d_res = _build(result[0],result[1],result[2],result[3], 0, 1e-6)
        result[3] = d_res.mu_1
    return result
