import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactDOM from 'react-dom/client';
import { motion, AnimatePresence, useMotionValue, useSpring, useTransform, useAnimation } from 'framer-motion';

const e = React.createElement;

// ── Constants ──────────────────────────────────────────────────────────────────
const RECONNECT_MS = 3500;

const SERVICES = [
  { name: 'Gmail',    color: '#ea4335', tools: 5,  char: 'M' },
  { name: 'Drive',    color: '#4285f4', tools: 5,  char: 'D' },
  { name: 'Calendar', color: '#0f9d58', tools: 5,  char: 'C' },
  { name: 'Photos',   color: '#fbbc04', tools: 3,  char: 'P' },
  { name: 'Tasks',    color: '#ff6d00', tools: 4,  char: 'T' },
  { name: 'Contacts', color: '#46bdc6', tools: 2,  char: 'K' },
];

const QUICK_ACTIONS = [
  { char: 'M', color: '#ea4335', label: 'Unread emails today',  prompt: 'Show my unread emails from today' },
  { char: 'C', color: '#0f9d58', label: "Today's schedule",      prompt: "What's on my calendar today and tomorrow?" },
  { char: 'D', color: '#4285f4', label: 'Recent Drive files',    prompt: 'List my recent Google Drive files' },
  { char: 'T', color: '#ff6d00', label: 'Pending tasks',         prompt: 'Show all my pending tasks' },
  { char: 'P', color: '#fbbc04', label: 'Photo albums',          prompt: 'List my photo albums' },
  { char: 'K', color: '#46bdc6', label: 'All contacts',          prompt: 'List all my contacts' },
];

const CHIPS = [
  'Summarize my last 5 emails',
  'Create a meeting tomorrow at 3 PM',
  'Search Drive for budget files',
  'Show tasks due this week',
];

// ── Helpers ────────────────────────────────────────────────────────────────────
function mdParse(text) {
  try {
    return window.marked ? window.marked.parse(text) : `<p>${text}</p>`;
  } catch {
    return `<p>${text}</p>`;
  }
}

// ── Hooks ──────────────────────────────────────────────────────────────────────
function use3DTilt(factor = 12) {
  const rx = useMotionValue(0);
  const ry = useMotionValue(0);
  const srx = useSpring(rx, { stiffness: 200, damping: 25 });
  const sry = useSpring(ry, { stiffness: 200, damping: 25 });

  const onMove = useCallback(evt => {
    const r = evt.currentTarget.getBoundingClientRect();
    rx.set(-(((evt.clientY - r.top)  / r.height) - 0.5) * factor);
    ry.set( (((evt.clientX - r.left) / r.width)  - 0.5) * factor);
  }, [rx, ry, factor]);

  const onLeave = useCallback(() => { rx.set(0); ry.set(0); }, [rx, ry]);
  return { rotateX: srx, rotateY: sry, onMouseMove: onMove, onMouseLeave: onLeave };
}

// ── ParticleCanvas ─────────────────────────────────────────────────────────────
function ParticleCanvas() {
  const ref = useRef(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext('2d');
    let raf;
    const resize = () => { c.width = window.innerWidth; c.height = window.innerHeight; };
    resize();
    window.addEventListener('resize', resize);

    const pts = Array.from({ length: 72 }, () => ({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      vx: (Math.random() - .5) * .25,
      vy: (Math.random() - .5) * .25,
      r: Math.random() * 1.2 + .4,
    }));

    const tick = () => {
      ctx.clearRect(0, 0, c.width, c.height);
      pts.forEach(p => {
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > c.width)  p.vx *= -1;
        if (p.y < 0 || p.y > c.height) p.vy *= -1;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(99,102,241,.32)';
        ctx.fill();
      });
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (d < 130) {
            ctx.strokeStyle = `rgba(99,102,241,${.07 * (1 - d / 130)})`;
            ctx.lineWidth = .6;
            ctx.beginPath();
            ctx.moveTo(pts[i].x, pts[i].y);
            ctx.lineTo(pts[j].x, pts[j].y);
            ctx.stroke();
          }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); };
  }, []);

  return e('canvas', { ref, style: { position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none' } });
}

// ── Aurora ─────────────────────────────────────────────────────────────────────
function Aurora() {
  const blobs = [
    { grad: '#6366f1,#7c3aed', w: 600, style: { top: '-15%', left: '-8%' },  delay: 0   },
    { grad: '#06b6d4,#0891b2', w: 480, style: { bottom: '-10%', right: '-8%' }, delay: -7  },
    { grad: '#8b5cf6,#4f46e5', w: 360, style: { top: '42%', left: '38%' },   delay: -14 },
  ];
  return e('div', { style: { position: 'fixed', inset: 0, zIndex: 0, overflow: 'hidden', pointerEvents: 'none' } },
    blobs.map((b, i) => e(motion.div, {
      key: i,
      style: {
        position: 'absolute',
        width: b.w, height: b.w,
        borderRadius: '50%',
        background: `radial-gradient(circle,${b.grad})`,
        filter: 'blur(80px)',
        opacity: .11,
        ...b.style,
      },
      animate: { x: [0, 30, -25, 0], y: [0, -25, 30, 0], scale: [1, 1.07, .94, 1] },
      transition: { duration: 20 + i * 7, repeat: Infinity, ease: 'easeInOut', delay: b.delay },
    }))
  );
}

// ── AuthScreen ─────────────────────────────────────────────────────────────────
function AuthScreen() {
  const tilt = use3DTilt(10);

  return e(motion.div, {
    key: 'auth',
    style: {
      position: 'fixed', inset: 0, zIndex: 10,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    },
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
  },
    /* Orbiting ring */
    e(motion.div, {
      style: {
        position: 'absolute',
        width: 520, height: 520,
        borderRadius: '50%',
        border: '1px dashed rgba(99,102,241,.18)',
      },
      animate: { rotate: 360 },
      transition: { duration: 32, repeat: Infinity, ease: 'linear' },
    },
      SERVICES.map((svc, i) => {
        const rad = ((i / SERVICES.length) * 360 * Math.PI) / 180;
        const r = 254;
        return e(motion.div, {
          key: svc.name,
          style: {
            position: 'absolute',
            left: `calc(50% + ${Math.cos(rad) * r}px - 18px)`,
            top:  `calc(50% + ${Math.sin(rad) * r}px - 18px)`,
            width: 36, height: 36, borderRadius: '50%',
            background: svc.color + '1a',
            border: `1px solid ${svc.color}55`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 11, fontWeight: 700, color: svc.color,
            backdropFilter: 'blur(6px)',
          },
          animate: { rotate: -360 },
          transition: { duration: 32, repeat: Infinity, ease: 'linear' },
        }, svc.char);
      })
    ),

    /* 3D tilt container */
    e('div', {
      style: { perspective: 1200, zIndex: 2 },
      onMouseMove: tilt.onMouseMove,
      onMouseLeave: tilt.onMouseLeave,
    },
      e(motion.div, {
        style: {
          rotateX: tilt.rotateX,
          rotateY: tilt.rotateY,
          transformStyle: 'preserve-3d',
          width: 420,
          background: 'rgba(10,16,38,.9)',
          backdropFilter: 'blur(32px)',
          WebkitBackdropFilter: 'blur(32px)',
          border: '1px solid rgba(99,102,241,.28)',
          borderRadius: 28,
          padding: '44px 40px',
          boxShadow: '0 0 80px rgba(99,102,241,.13), 0 40px 80px rgba(0,0,0,.55)',
          textAlign: 'center',
        },
        initial: { scale: .84, opacity: 0, y: 40 },
        animate: { scale: 1, opacity: 1, y: 0 },
        transition: { type: 'spring', stiffness: 190, damping: 25, delay: .15 },
      },
        /* Icon */
        e(motion.div, {
          style: { display: 'flex', justifyContent: 'center', marginBottom: 22 },
          initial: { scale: 0, rotate: -180 },
          animate: { scale: 1, rotate: 0 },
          transition: { type: 'spring', stiffness: 200, damping: 20, delay: .38 },
        },
          e('div', {
            style: {
              width: 70, height: 70, borderRadius: '50%',
              background: 'linear-gradient(135deg,#ea4335,#fbbc04,#34a853,#4285f4)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 0 40px rgba(99,102,241,.45)',
            },
          },
            e('svg', { width: 34, height: 34, viewBox: '0 0 48 48' },
              e('path', { fill: 'white', d: 'M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z' }),
              e('path', { fill: 'white', d: 'M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z' }),
              e('path', { fill: 'white', d: 'M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z' }),
              e('path', { fill: 'white', d: 'M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z' })
            )
          )
        ),

        /* Title */
        e(motion.h1, {
          style: {
            fontFamily: "'Space Grotesk', sans-serif",
            fontSize: 23, fontWeight: 700, marginBottom: 11,
            background: 'linear-gradient(135deg,#f1f5f9,#a5b4fc)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          },
          initial: { opacity: 0, y: 10 },
          animate: { opacity: 1, y: 0 },
          transition: { delay: .5 },
        }, 'Google Services AI Agent'),

        /* Desc */
        e(motion.p, {
          style: { color: 'rgba(241,245,249,.52)', fontSize: 13.5, lineHeight: 1.65, marginBottom: 30 },
          initial: { opacity: 0, y: 10 },
          animate: { opacity: 1, y: 0 },
          transition: { delay: .6 },
        }, 'Connect your Google account for AI-powered access to Gmail, Drive, Calendar, Photos, Tasks and Contacts.'),

        /* Button */
        e(motion.a, {
          href: '/auth/login',
          style: {
            display: 'inline-flex', alignItems: 'center', gap: 10,
            padding: '13px 26px',
            background: 'linear-gradient(135deg,#6366f1,#8b5cf6)',
            borderRadius: 14, color: 'white',
            fontWeight: 600, fontSize: 14.5,
            textDecoration: 'none',
            boxShadow: '0 8px 32px rgba(99,102,241,.48)',
          },
          whileHover: { scale: 1.04, boxShadow: '0 12px 40px rgba(99,102,241,.68)' },
          whileTap: { scale: .97 },
          initial: { opacity: 0, y: 10 },
          animate: { opacity: 1, y: 0 },
          transition: { delay: .7 },
        },
          e('svg', { width: 17, height: 17, viewBox: '0 0 48 48' },
            e('path', { fill: '#EA4335', d: 'M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z' }),
            e('path', { fill: '#4285F4', d: 'M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z' }),
            e('path', { fill: '#FBBC05', d: 'M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z' }),
            e('path', { fill: '#34A853', d: 'M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z' })
          ),
          'Sign in with Google'
        ),

        /* Services pills */
        e(motion.div, {
          style: { display: 'flex', flexWrap: 'wrap', gap: 7, justifyContent: 'center', marginTop: 26 },
          initial: { opacity: 0 },
          animate: { opacity: 1 },
          transition: { delay: .85 },
        },
          SERVICES.map((s, i) => e(motion.span, {
            key: s.name,
            style: {
              padding: '3px 11px', borderRadius: 20,
              background: s.color + '1a', border: `1px solid ${s.color}40`,
              color: s.color, fontSize: 11.5, fontWeight: 600,
            },
            initial: { scale: 0, opacity: 0 },
            animate: { scale: 1, opacity: 1 },
            transition: { delay: .9 + i * .04, type: 'spring', stiffness: 350 },
            whileHover: { scale: 1.1 },
          }, s.name))
        ),

        /* Footer token note */
        e(motion.p, {
          style: { color: 'rgba(241,245,249,.28)', fontSize: 11.5, marginTop: 22 },
          initial: { opacity: 0 },
          animate: { opacity: 1 },
          transition: { delay: 1 },
        }, 'Token stored locally in ', e('code', { style: { color: 'rgba(165,180,252,.72)', fontSize: 11 } }, 'config/token.json'))
      )
    )
  );
}

// ── StatusPill ─────────────────────────────────────────────────────────────────
function StatusPill({ state, text }) {
  const clr = ({ connected: '#22c55e', connecting: '#f59e0b', error: '#ef4444' })[state] || '#f59e0b';
  return e('div', {
    style: {
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '5px 12px',
      background: 'rgba(255,255,255,.05)',
      border: '1px solid rgba(255,255,255,.09)',
      borderRadius: 20, fontSize: 12, color: 'rgba(241,245,249,.62)',
    },
  },
    e('div', { style: { position: 'relative', width: 8, height: 8, flexShrink: 0 } },
      e('div', { style: { width: 8, height: 8, borderRadius: '50%', background: clr } }),
      state === 'connected' && e(motion.div, {
        style: { position: 'absolute', inset: -3, borderRadius: '50%', border: `1px solid ${clr}` },
        animate: { scale: [1, 1.9], opacity: [.8, 0] },
        transition: { duration: 1.5, repeat: Infinity },
      })
    ),
    e('span', null, text)
  );
}

// ── Sidebar ────────────────────────────────────────────────────────────────────
function Sidebar({ wsState, statusTxt, onAction, onNewChat }) {
  return e(motion.aside, {
    style: {
      width: 270, flexShrink: 0,
      display: 'flex', flexDirection: 'column',
      background: 'rgba(7,12,28,.9)',
      backdropFilter: 'blur(24px)',
      WebkitBackdropFilter: 'blur(24px)',
      borderRight: '1px solid rgba(255,255,255,.07)',
      position: 'relative', zIndex: 5,
      overflow: 'hidden',
    },
    initial: { x: -280 },
    animate: { x: 0 },
    transition: { type: 'spring', stiffness: 200, damping: 30 },
  },
    e('div', {
      style: {
        position: 'absolute', top: 0, insetInline: 0, height: 220,
        background: 'linear-gradient(180deg,rgba(99,102,241,.07),transparent)',
        pointerEvents: 'none',
      },
    }),

    e('div', { style: { padding: '22px 18px 18px', flexShrink: 0 } },
      e('div', { style: { display: 'flex', alignItems: 'center', gap: 11, marginBottom: 18 } },
        e(motion.div, {
          style: {
            width: 40, height: 40, borderRadius: 12,
            background: 'linear-gradient(135deg,#6366f1,#8b5cf6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 4px 20px rgba(99,102,241,.42)',
          },
          whileHover: { scale: 1.06, rotate: 6 },
        },
          e('svg', { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none' },
            e('path', { d: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5', stroke: 'white', strokeWidth: '2', strokeLinecap: 'round', strokeLinejoin: 'round' })
          )
        ),
        e('div', null,
          e('div', { style: { fontFamily: "'Space Grotesk',sans-serif", fontWeight: 700, fontSize: 15, color: '#f1f5f9' } }, 'Google Agent'),
          e('div', { style: { fontSize: 11, color: 'rgba(241,245,249,.38)', marginTop: 1 } }, 'AI Personal Assistant')
        )
      ),
      e(StatusPill, { state: wsState, text: statusTxt })
    ),

    e('div', { style: { flex: 1, overflowY: 'auto', padding: '0 18px 16px' } },
      e('div', { style: { marginBottom: 22 } },
        e('div', { style: { fontSize: 10.5, fontWeight: 600, color: 'rgba(241,245,249,.28)', letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 8 } }, 'Connected Services'),
        SERVICES.map((s, i) => e(motion.div, {
          key: s.name,
          style: { display: 'flex', alignItems: 'center', gap: 10, padding: '7px 9px', borderRadius: 9, cursor: 'default' },
          initial: { x: -20, opacity: 0 },
          animate: { x: 0, opacity: 1 },
          transition: { delay: .1 + i * .04, type: 'spring', stiffness: 300 },
          whileHover: { background: 'rgba(255,255,255,.05)', x: 3 },
        },
          e('div', { style: { width: 7, height: 7, borderRadius: '50%', background: s.color, boxShadow: `0 0 8px ${s.color}90`, flexShrink: 0 } }),
          e('span', { style: { flex: 1, fontSize: 12.5, color: 'rgba(241,245,249,.76)', fontWeight: 500 } }, s.name),
          e('span', { style: { fontSize: 10.5, color: 'rgba(241,245,249,.32)', background: 'rgba(255,255,255,.07)', padding: '1px 6px', borderRadius: 9 } }, s.tools)
        ))
      ),

      e('div', null,
        e('div', { style: { fontSize: 10.5, fontWeight: 600, color: 'rgba(241,245,249,.28)', letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 8 } }, 'Quick Actions'),
        QUICK_ACTIONS.map((qa, i) => e(motion.button, {
          key: qa.label,
          onClick: () => onAction(qa.prompt),
          style: { width: '100%', textAlign: 'left', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 9, padding: '7px 9px', borderRadius: 9, background: 'transparent', color: 'rgba(241,245,249,.66)', fontSize: 12 },
          initial: { x: -20, opacity: 0 },
          animate: { x: 0, opacity: 1 },
          transition: { delay: .38 + i * .04, type: 'spring', stiffness: 300 },
          whileHover: { background: 'rgba(255,255,255,.05)', x: 3, color: '#f1f5f9' },
          whileTap: { scale: .97 },
        },
          e('span', { style: { width: 22, height: 22, borderRadius: 6, flexShrink: 0, background: qa.color + '1c', border: `1px solid ${qa.color}40`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, color: qa.color } }, qa.char),
          e('span', { style: { fontWeight: 500 } }, qa.label)
        ))
      )
    ),

    e('div', { style: { padding: '14px 18px', borderTop: '1px solid rgba(255,255,255,.07)', flexShrink: 0 } },
      e(motion.button, {
        onClick: onNewChat,
        style: { width: '100%', padding: '9px', background: 'rgba(99,102,241,.1)', border: '1px solid rgba(99,102,241,.22)', borderRadius: 10, color: 'rgba(165,180,252,.82)', cursor: 'pointer', fontWeight: 600, fontSize: 12.5, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 },
        whileHover: { background: 'rgba(99,102,241,.2)', borderColor: 'rgba(99,102,241,.45)', scale: 1.01 },
        whileTap: { scale: .97 },
      },
        e('svg', { width: 12, height: 12, viewBox: '0 0 24 24', fill: 'none' },
          e('path', { d: 'M12 5v14M5 12h14', stroke: 'currentColor', strokeWidth: '2.5', strokeLinecap: 'round' })
        ),
        'New Conversation'
      )
    )
  );
}

// ── Service Cards Grid Component (Flat Layout, No Rolling) ───────────────────
const TOOL_CARDS = [
  { name: 'Gmail',    prompt: 'Show my unread emails from today',          img: 'https://images.unsplash.com/photo-1596526131083-e8c633c948d2?w=500&auto=format&fit=crop&q=80', color: '#ea4335' },
  { name: 'Drive',    prompt: 'List my recent Google Drive files',         img: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=500&auto=format&fit=crop&q=80', color: '#4285f4' },
  { name: 'Calendar', prompt: "What's on my calendar today and tomorrow?",  img: 'https://images.unsplash.com/photo-1506784983877-45594efa4cbe?w=500&auto=format&fit=crop&q=80', color: '#0f9d58' },
  { name: 'Photos',   prompt: 'List my photo albums',                      img: 'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=500&auto=format&fit=crop&q=80', color: '#fbbc04' },
  { name: 'Tasks',    prompt: 'Show all my pending tasks',                 img: 'https://images.unsplash.com/photo-1484480974693-6ca0a78fb36b?w=500&auto=format&fit=crop&q=80', color: '#ff6d00' },
  { name: 'Contacts', prompt: 'List all my contacts',                      img: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=500&auto=format&fit=crop&q=80', color: '#46bdc6' },
];

function ServiceCardsGrid({ onSelect }) {
  return e('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))',
      gap: 12,
      margin: '18px 0 22px',
      width: '100%',
    },
  },
    TOOL_CARDS.map((card, i) => e(motion.div, {
      key: card.name,
      onClick: () => onSelect(card.prompt),
      style: {
        background: 'rgba(10,16,38,.85)',
        border: `1px solid ${card.color}40`,
        borderRadius: 16,
        padding: 10,
        textAlign: 'left',
        cursor: 'pointer',
        boxShadow: `0 4px 20px rgba(0,0,0,.3), 0 0 15px ${card.color}15`,
        overflow: 'hidden',
      },
      initial: { opacity: 0, y: 15 },
      animate: { opacity: 1, y: 0 },
      transition: { delay: .15 + i * .05, type: 'spring', stiffness: 300 },
      whileHover: { scale: 1.04, borderColor: card.color, boxShadow: `0 8px 25px ${card.color}35` },
      whileTap: { scale: .97 },
    },
      e('div', { style: { height: 85, borderRadius: 10, overflow: 'hidden', marginBottom: 8 } },
        e('img', {
          src: card.img, alt: card.name,
          style: { width: '100%', height: '100%', objectFit: 'cover' },
        })
      ),
      e('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' } },
        e('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
          e('div', { style: { width: 7, height: 7, borderRadius: '50%', background: card.color } }),
          e('span', { style: { fontWeight: 700, fontSize: 13, color: '#f1f5f9' } }, card.name)
        ),
        e('span', { style: { fontSize: 9.5, color: card.color, background: card.color + '1a', padding: '1px 6px', borderRadius: 4, fontWeight: 600 } }, 'Service')
      )
    ))
  );
}

// ── WelcomeCard ────────────────────────────────────────────────────────────────
function WelcomeCard({ onChip }) {
  return e(motion.div, {
    style: {
      maxWidth: 580, margin: 'auto',
      background: 'rgba(10,16,38,.65)',
      backdropFilter: 'blur(24px)',
      WebkitBackdropFilter: 'blur(24px)',
      border: '1px solid rgba(99,102,241,.18)',
      borderRadius: 24, padding: '30px 24px', textAlign: 'center',
    },
    initial: { scale: .88, opacity: 0, y: 20 },
    animate: { scale: 1, opacity: 1, y: 0 },
    exit: { scale: .9, opacity: 0, y: -20, transition: { duration: .18 } },
    transition: { type: 'spring', stiffness: 200, damping: 25 },
  },
    e('div', {
      style: {
        width: 54, height: 54, borderRadius: '50%',
        background: 'linear-gradient(135deg,rgba(99,102,241,.22),rgba(139,92,246,.22))',
        border: '1px solid rgba(99,102,241,.28)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        margin: '0 auto 14px',
      },
    },
      e('svg', { width: 24, height: 24, viewBox: '0 0 24 24', fill: 'none' },
        e('defs', null,
          e('linearGradient', { id: 'wg', x1: '0%', y1: '0%', x2: '100%', y2: '100%' },
            e('stop', { offset: '0%', stopColor: '#6366f1' }),
            e('stop', { offset: '100%', stopColor: '#8b5cf6' })
          )
        ),
        e('path', { d: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5', stroke: 'url(#wg)', strokeWidth: '1.5', strokeLinecap: 'round', strokeLinejoin: 'round' })
      )
    ),

    e('h2', { style: { fontFamily: "'Space Grotesk',sans-serif", fontSize: 19, fontWeight: 700, color: '#f1f5f9', marginBottom: 6 } }, 'Your AI-Powered Google Assistant'),
    e('p', { style: { color: 'rgba(241,245,249,.5)', fontSize: 13, lineHeight: 1.5, marginBottom: 14 } }, 'I have live access to Gmail, Drive, Calendar, Photos, Tasks and Contacts. Select a service below or type your request!'),

    /* Flat Service Cards Grid */
    e(ServiceCardsGrid, { onSelect: onChip }),

    e('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center' } },
      CHIPS.map((chip, i) => e(motion.button, {
        key: chip,
        onClick: () => onChip(chip),
        style: {
          padding: '6px 12px',
          background: 'rgba(99,102,241,.1)',
          border: '1px solid rgba(99,102,241,.22)',
          borderRadius: 20, color: 'rgba(165,180,252,.82)',
          cursor: 'pointer', fontSize: 11.5, fontWeight: 500,
        },
        initial: { scale: 0, opacity: 0 },
        animate: { scale: 1, opacity: 1 },
        transition: { delay: .3 + i * .07, type: 'spring', stiffness: 400 },
        whileHover: { background: 'rgba(99,102,241,.2)', scale: 1.06, color: '#a5b4fc' },
      }, `"${chip}"`))
    )
  );
}

// ── TypingIndicator ────────────────────────────────────────────────────────────
function TypingIndicator() {
  return e(motion.div, {
    style: { display: 'flex', gap: 10, alignItems: 'flex-end' },
    initial: { opacity: 0, y: 10 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: 10 },
  },
    e('div', { style: { width: 32, height: 32, borderRadius: '50%', flexShrink: 0, background: 'linear-gradient(135deg,#6366f1,#8b5cf6)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, color: 'white', boxShadow: '0 0 14px rgba(99,102,241,.42)', marginTop: 2 } }, 'AI'),
    e('div', { style: { background: 'rgba(10,16,38,.82)', backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)', border: '1px solid rgba(255,255,255,.09)', borderRadius: '18px 18px 18px 4px', padding: '13px 17px', display: 'flex', gap: 5, alignItems: 'center' } },
      [0, 1, 2].map(i => e(motion.div, {
        key: i,
        style: { width: 7, height: 7, borderRadius: '50%', background: 'rgba(99,102,241,.72)' },
        animate: { y: [0, -7, 0], opacity: [.5, 1, .5] },
        transition: { duration: .8, repeat: Infinity, delay: i * .15, ease: 'easeInOut' },
      }))
    )
  );
}

// ── MessageBubble ──────────────────────────────────────────────────────────────
function MessageBubble({ role, content }) {
  const isUser = role === 'user';
  const mdRef = useRef(null);

  useEffect(() => {
    if (!isUser && mdRef.current && window.hljs) {
      mdRef.current.querySelectorAll('pre code').forEach(b => window.hljs.highlightElement(b));
      mdRef.current.querySelectorAll('a[href]').forEach(a => {
        if (a.hostname !== location.hostname) a.target = '_blank';
      });
    }
  }, [content, isUser]);

  return e(motion.div, {
    style: {
      display: 'flex',
      flexDirection: isUser ? 'row-reverse' : 'row',
      gap: 10, alignItems: 'flex-start',
    },
    initial: { opacity: 0, x: isUser ? 40 : -40, scale: .94 },
    animate: { opacity: 1, x: 0, scale: 1 },
    transition: { type: 'spring', stiffness: 280, damping: 28 },
  },
    e(motion.div, {
      style: {
        width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
        background: isUser ? 'linear-gradient(135deg,#374151,#4b5563)' : 'linear-gradient(135deg,#6366f1,#8b5cf6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 10, fontWeight: 700, color: 'white',
        boxShadow: isUser ? 'none' : '0 0 14px rgba(99,102,241,.42)',
        marginTop: 2,
      },
      whileHover: { scale: 1.1 },
    }, isUser ? 'You' : 'AI'),

    e(motion.div, {
      style: {
        maxWidth: '70%',
        padding: isUser ? '10px 15px' : '13px 17px',
        borderRadius: isUser ? '18px 4px 18px 18px' : '4px 18px 18px 18px',
        background: isUser ? 'linear-gradient(135deg,#6366f1,#8b5cf6)' : 'rgba(10,16,38,.8)',
        backdropFilter: isUser ? 'none' : 'blur(16px)',
        WebkitBackdropFilter: isUser ? 'none' : 'blur(16px)',
        border: isUser ? 'none' : '1px solid rgba(255,255,255,.09)',
        boxShadow: isUser ? '0 4px 24px rgba(99,102,241,.42)' : '0 4px 24px rgba(0,0,0,.32)',
        fontSize: 14, lineHeight: 1.65,
        color: isUser ? 'rgba(255,255,255,.95)' : '#f1f5f9',
        wordBreak: 'break-word',
      },
      whileHover: { scale: 1.005 },
      transition: { type: 'spring', stiffness: 400 },
    },
      isUser
        ? e('span', null, content)
        : e('div', { ref: mdRef, className: 'md-content', dangerouslySetInnerHTML: { __html: mdParse(content) } })
    )
  );
}

// ── ErrorRow ───────────────────────────────────────────────────────────────────
function ErrorRow({ text }) {
  return e(motion.div, {
    style: {
      display: 'flex', alignItems: 'center', gap: 7,
      padding: '9px 15px', borderRadius: 11,
      background: 'rgba(239,68,68,.1)', border: '1px solid rgba(239,68,68,.24)',
      color: 'rgba(252,165,165,.9)', fontSize: 13,
      maxWidth: '65%', alignSelf: 'center',
    },
    initial: { opacity: 0, scale: .9 },
    animate: { opacity: 1, scale: 1 },
  }, `⚠ ${text}`);
}

// ── InputArea ──────────────────────────────────────────────────────────────────
function InputArea({ onSend, isReady }) {
  const [val, setVal] = useState('');
  const [focused, setFocused] = useState(false);
  const taRef = useRef(null);

  const canSend = val.trim().length > 0 && isReady;

  const resize = () => {
    if (!taRef.current) return;
    taRef.current.style.height = 'auto';
    taRef.current.style.height = Math.min(taRef.current.scrollHeight, 160) + 'px';
  };

  const doSend = () => {
    const text = val.trim();
    if (!text || !isReady) return;
    onSend(text);
    setVal('');
    setTimeout(() => { if (taRef.current) taRef.current.style.height = 'auto'; }, 0);
  };

  return e(motion.div, {
    style: { padding: '14px 20px 18px', flexShrink: 0 },
    initial: { y: 60, opacity: 0 },
    animate: { y: 0, opacity: 1 },
    transition: { type: 'spring', stiffness: 200, damping: 30, delay: .25 },
  },
    e('div', {
      style: {
        display: 'flex', gap: 10, alignItems: 'flex-end',
        background: 'rgba(10,16,38,.78)',
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
        border: `1px solid ${focused ? 'rgba(99,102,241,.5)' : 'rgba(255,255,255,.09)'}`,
        borderRadius: 18, padding: '9px 11px 9px 17px',
        transition: 'border-color .2s, box-shadow .2s',
        boxShadow: focused ? '0 0 32px rgba(99,102,241,.18)' : 'none',
      },
    },
      e('textarea', {
        ref: taRef,
        value: val,
        onInput: eEvt => { setVal(eEvt.target.value); resize(); },
        onKeyDown: eEvt => { if (eEvt.key === 'Enter' && !eEvt.shiftKey) { eEvt.preventDefault(); doSend(); } },
        onFocus: () => setFocused(true),
        onBlur: () => setFocused(false),
        rows: 1,
        maxLength: 4000,
        placeholder: 'Ask about your Gmail, Calendar, Drive, Photos, Tasks or Contacts…',
        style: {
          flex: 1, resize: 'none', border: 'none', outline: 'none',
          background: 'transparent', color: '#f1f5f9',
          fontSize: 14, lineHeight: 1.5,
          fontFamily: 'Inter, system-ui, sans-serif',
          minHeight: 22,
        },
        'aria-label': 'Message input',
      }),
      e(motion.button, {
        onClick: doSend,
        disabled: !canSend,
        style: {
          width: 37, height: 37, borderRadius: 11, flexShrink: 0,
          background: canSend ? 'linear-gradient(135deg,#6366f1,#8b5cf6)' : 'rgba(255,255,255,.08)',
          border: 'none', cursor: canSend ? 'pointer' : 'not-allowed',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: canSend ? 'white' : 'rgba(255,255,255,.22)',
          boxShadow: canSend ? '0 4px 16px rgba(99,102,241,.48)' : 'none',
          transition: 'background .2s, box-shadow .2s',
        },
        whileHover: canSend ? { scale: 1.09, rotate: 8 } : {},
        whileTap: canSend ? { scale: .92 } : {},
        'aria-label': 'Send message',
      },
        e('svg', { width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none' },
          e('path', { d: 'M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z', stroke: 'currentColor', strokeWidth: '2', strokeLinecap: 'round', strokeLinejoin: 'round' })
        )
      )
    ),
    e('div', { style: { textAlign: 'center', marginTop: 7, fontSize: 11, color: 'rgba(241,245,249,.2)' } },
      'Press ', e('kbd', null, 'Enter'), ' to send · ', e('kbd', null, 'Shift+Enter'), ' for new line'
    )
  );
}

// ── ChatApp ────────────────────────────────────────────────────────────────────
function ChatApp() {
  const [msgs,       setMsgs]      = useState([]);
  const [typing,     setTyping]    = useState(false);
  const [wsState,    setWsState]   = useState('connecting');
  const [statusTxt,  setStatusTxt] = useState('Connecting…');
  const [ready,      setReady]     = useState(false);
  const [showWelcome,setShowWelcome] = useState(true);

  const wsRef    = useRef(null);
  const endRef   = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [msgs, typing]);

  const onMsg = useCallback(msg => {
    switch (msg.type) {
      case 'auth_required': location.reload(); break;
      case 'status':  setWsState('connecting'); setStatusTxt(msg.message); break;
      case 'ready':   setReady(true); setWsState('connected'); setStatusTxt('Connected'); break;
      case 'typing':  setTyping(true); break;
      case 'message': setTyping(false); setMsgs(p => [...p, { kind: 'msg', role: msg.role, content: msg.content }]); break;
      case 'error':   setTyping(false); setMsgs(p => [...p, { kind: 'err', content: msg.message }]); break;
    }
  }, []);

  const connect = useCallback(() => {
    setWsState('connecting'); setStatusTxt('Connecting…');
    const ws = new WebSocket(`ws://${location.host}/ws`);
    wsRef.current = ws;
    ws.onmessage = evt => { try { onMsg(JSON.parse(evt.data)); } catch {} };
    ws.onclose   = () => {
      setReady(false); setWsState('error'); setStatusTxt('Disconnected');
      timerRef.current = setTimeout(connect, RECONNECT_MS);
    };
    ws.onerror   = () => { setWsState('error'); setStatusTxt('Connection error'); };
  }, [onMsg]);

  useEffect(() => {
    connect();
    return () => { clearTimeout(timerRef.current); wsRef.current?.close(); };
  }, [connect]);

  const send = useCallback(text => {
    if (!text || !ready || wsRef.current?.readyState !== WebSocket.OPEN) return;
    setShowWelcome(false);
    setMsgs(p => [...p, { kind: 'msg', role: 'user', content: text }]);
    wsRef.current.send(JSON.stringify({ type: 'message', content: text }));
  }, [ready]);

  return e(motion.div, {
    key: 'chat',
    style: { display: 'flex', height: '100vh', position: 'relative', zIndex: 5 },
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
  },
    e(Sidebar, { wsState, statusTxt, onAction: send, onNewChat: () => location.reload() }),

    e('main', { style: { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 } },
      e(motion.header, {
        style: {
          padding: '13px 22px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'rgba(6,10,22,.68)',
          backdropFilter: 'blur(14px)',
          WebkitBackdropFilter: 'blur(14px)',
          borderBottom: '1px solid rgba(255,255,255,.07)',
          flexShrink: 0,
        },
        initial: { y: -60 },
        animate: { y: 0 },
        transition: { type: 'spring', stiffness: 200, damping: 30 },
      },
        e('div', null,
          e('h1', {
            style: {
              fontFamily: "'Space Grotesk',sans-serif",
              fontSize: 17, fontWeight: 700, margin: 0,
              background: 'linear-gradient(90deg,#f1f5f9,#a5b4fc)',
              WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            },
          }, 'Google Services AI'),
          e('p', { style: { fontSize: 11, color: 'rgba(241,245,249,.36)', margin: '2px 0 0' } }, 'Powered by Groq · LLaMA 3.3-70B')
        ),

        e(motion.div, {
          style: {
            padding: '4px 13px',
            background: 'rgba(99,102,241,.1)',
            border: '1px solid rgba(99,102,241,.22)',
            borderRadius: 20, fontSize: 11.5, fontWeight: 600,
            color: 'rgba(165,180,252,.78)',
          },
          animate: { opacity: [.7, 1, .7] },
          transition: { duration: 2, repeat: Infinity },
        }, '24 Tools Active')
      ),

      e('div', {
        style: {
          flex: 1, overflowY: 'auto',
          padding: '18px 22px',
          display: 'flex', flexDirection: 'column', gap: 10,
        },
      },
        e(AnimatePresence, null,
          showWelcome && msgs.length === 0 ? e(WelcomeCard, { key: 'wc', onChip: send }) : null
        ),

        e(AnimatePresence, { initial: false },
          msgs.map((m, i) => (
            m.kind === 'err'
              ? e(ErrorRow, { key: i, text: m.content })
              : e(MessageBubble, { key: i, role: m.role, content: m.content })
          )),
          typing ? e(TypingIndicator, { key: '__typing__' }) : null
        ),

        e('div', { ref: endRef })
      ),

      e(InputArea, { onSend: send, isReady: ready })
    )
  );
}

// ── Root App ───────────────────────────────────────────────────────────────────
function App() {
  const [authed, setAuthed] = useState(null);

  useEffect(() => {
    fetch('/api/auth-status')
      .then(r => r.json())
      .then(d => setAuthed(d.authenticated))
      .catch(() => setAuthed(false));
  }, []);

  if (authed === null) {
    return e(React.Fragment, null,
      e(Aurora),
      e('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', zIndex: 5, position: 'relative' } },
        e(motion.div, {
          style: {
            width: 38, height: 38, borderRadius: '50%',
            border: '3px solid rgba(99,102,241,.22)',
            borderTopColor: '#6366f1',
          },
          animate: { rotate: 360 },
          transition: { duration: .75, repeat: Infinity, ease: 'linear' },
        })
      )
    );
  }

  return e(React.Fragment, null,
    e(Aurora),
    e(ParticleCanvas),
    e(AnimatePresence, { mode: 'wait' },
      authed
        ? e(ChatApp, { key: 'chat' })
        : e(AuthScreen, { key: 'auth' })
    )
  );
}

// ── Mount ──────────────────────────────────────────────────────────────────────
ReactDOM.createRoot(document.getElementById('root')).render(e(App));
