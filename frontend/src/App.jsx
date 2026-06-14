import { useState, useCallback, useEffect } from 'react'
import axios from 'axios'
import './App.css'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const MOOD_CONFIG = {
  THRIVING:     { label: 'Thriving',        color: '#15803D', bg: '#F0FDF4', emoji: '🌸' },
  STABLE:       { label: 'Stable',          color: '#1D4ED8', bg: '#EFF6FF', emoji: '🌿' },
  CONCERNED:    { label: 'Concerned',       color: '#B45309', bg: '#FFFBEB', emoji: '☁️' },
  CHAOS:        { label: 'Chaos Mode',      color: '#C2410C', bg: '#FFF7ED', emoji: '⚡' },
  INTERVENTION: { label: 'Needs Attention', color: '#B91C1C', bg: '#FEF2F2', emoji: '🚨' },
}

const CATEGORY_COLORS = {
  'DSA':            { text: '#1D4ED8', border: '#93C5FD' },
  'System Design':  { text: '#C2410C', border: '#FDBA74' },
  'Fitness':        { text: '#15803D', border: '#86EFAC' },
  'Learning':       { text: '#0F766E', border: '#5EEAD4' },
  'Project':        { text: '#7C3AED', border: '#C4B5FD' },
  'Review':         { text: '#4B5563', border: '#D1D5DB' },
  'Practice':       { text: '#9D174D', border: '#F9A8D4' },
  'Research':       { text: '#4338CA', border: '#A5B4FC' },
}

function categoryStyle(category) {
  return CATEGORY_COLORS[category] ?? { text: '#7C3AED', border: '#C4B5FD' }
}

function PetalIcon({ className }) {
  return (
    <svg className={className ?? 'brand-icon'} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M16 3C16 3 11 8.5 11 14C11 17.3137 13.2386 19 16 19C18.7614 19 21 17.3137 21 14C21 8.5 16 3 16 3Z" fill="currentColor" opacity="0.95"/>
      <path d="M16 29C16 29 11 23.5 11 18C11 14.6863 13.2386 13 16 13C18.7614 13 21 14.6863 21 18C21 23.5 16 29 16 29Z" fill="currentColor" opacity="0.55"/>
      <path d="M3 16C3 16 8.5 11 14 11C17.3137 11 19 13.2386 19 16C19 18.7614 17.3137 21 14 21C8.5 21 3 16 3 16Z" fill="currentColor" opacity="0.75"/>
      <path d="M29 16C29 16 23.5 11 18 11C14.6863 11 13 13.2386 13 16C13 18.7614 14.6863 21 18 21C23.5 21 29 16 29 16Z" fill="currentColor" opacity="0.45"/>
    </svg>
  )
}

function TaskCard({ task, onStatusChange }) {
  const [status, setStatus] = useState(task.status || 'pending')
  const [showReasonForm, setShowReasonForm] = useState(false)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)

  const colors = categoryStyle(task.category)
  const timePart = task.scheduled_time.includes(',')
    ? task.scheduled_time.split(',').slice(1).join(',').trim()
    : task.scheduled_time

  async function updateStatus(newStatus, skipReason = null) {
    setSaving(true)
    try {
      const { data } = await axios.patch(`/tasks/${task.id}/status`, {
        status: newStatus,
        reason: skipReason,
      })
      setStatus(data.status)
      onStatusChange?.(task.id, data.status)
    } catch (e) {
      console.error('Status update failed:', e)
    }
    setSaving(false)
  }

  async function submitSkip() {
    await updateStatus('skipped', reason || null)
    setShowReasonForm(false)
    setReason('')
  }

  const isDone = status === 'done'
  const isSkipped = status === 'skipped'

  return (
    <div className={`task-card task-card--${status}`}>
      <p className="task-title">{task.title}</p>

      <div className="task-meta-row">
        <span
          className="task-category"
          style={{ background: 'transparent', color: colors.text, borderColor: colors.border }}
        >
          {task.category}
        </span>
        <span className="task-duration">{task.duration}m</span>
      </div>

      <span className="task-time">{timePart}</span>

      {showReasonForm && (
        <div className="reason-form">
          <input
            className="reason-input"
            placeholder="Why did you miss it? (optional)"
            value={reason}
            onChange={e => setReason(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submitSkip()}
            autoFocus
          />
          <div className="reason-actions">
            <button className="btn-ghost" onClick={() => { setShowReasonForm(false); setReason('') }}>
              Cancel
            </button>
            <button className="btn-skip-confirm" onClick={submitSkip} disabled={saving}>
              Confirm
            </button>
          </div>
        </div>
      )}

      {isSkipped && task.skip_reason && (
        <p className="skip-reason-display">"{task.skip_reason}"</p>
      )}

      {!showReasonForm && (
        <div className="task-actions">
          {isDone || isSkipped ? (
            <button className="btn-undo" onClick={() => updateStatus('pending')} disabled={saving}>
              Undo
            </button>
          ) : (
            <>
              <button className="btn-done" onClick={() => updateStatus('done')} disabled={saving}>
                Done
              </button>
              <button className="btn-missed" onClick={() => setShowReasonForm(true)} disabled={saving}>
                Missed
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function LoadingState({ text }) {
  return (
    <div className="loading-state">
      <div className="spinner-wrap">
        <div className="spinner-ring" />
        <PetalIcon className="spinner-petal" />
      </div>
      <p className="loading-text">{text}</p>
      <p className="loading-sub">This may take 20 – 40 seconds</p>
    </div>
  )
}

function MoodBadge({ mood }) {
  const cfg = MOOD_CONFIG[mood] || MOOD_CONFIG.STABLE
  return (
    <span
      className="mood-badge"
      style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.color + '50' }}
    >
      {cfg.emoji} {cfg.label}
    </span>
  )
}

function InsightsView({ data, onAdaptivePlan, adaptiveLoading }) {
  const { stats, insights, message, mood } = data
  const moodCfg = MOOD_CONFIG[mood] || MOOD_CONFIG.STABLE
  const pct = Math.round((stats.completion_rate || 0) * 100)

  return (
    <section className="insights-section">

      {/* Mood + progress hero */}
      <div className="insights-hero" style={{ borderLeftColor: moodCfg.color }}>
        <div className="insights-hero-top">
          <MoodBadge mood={mood} />
          <span className="insights-pct" style={{ color: moodCfg.color }}>{pct}%</span>
        </div>
        <div className="insights-bar-wrap">
          <div className="insights-bar">
            <div
              className="insights-bar-fill"
              style={{ width: `${pct}%`, background: moodCfg.color }}
            />
          </div>
        </div>
        <div className="insights-counts">
          <span className="count-chip count-chip--done">✓ {stats.done} done</span>
          <span className="count-chip count-chip--miss">✗ {stats.skipped} skipped</span>
          <span className="count-chip">{stats.pending} pending</span>
        </div>
      </div>

      {/* Not enough data notice */}
      {message && (
        <div className="insights-notice">{message}</div>
      )}

      {/* Key metrics */}
      {(stats.strongest_category || stats.best_time_slot) && (
        <div className="metrics-row">
          {stats.strongest_category && (
            <div className="metric-card metric-card--good">
              <p className="metric-label">Best Category</p>
              <p className="metric-value">{stats.strongest_category}</p>
            </div>
          )}
          {stats.weakest_category && stats.weakest_category !== stats.strongest_category && (
            <div className="metric-card metric-card--warn">
              <p className="metric-label">Needs Work</p>
              <p className="metric-value">{stats.weakest_category}</p>
            </div>
          )}
          {stats.best_time_slot && (
            <div className="metric-card metric-card--good">
              <p className="metric-label">Best Time Slot</p>
              <p className="metric-value">{stats.best_time_slot}</p>
            </div>
          )}
          {stats.worst_time_slot && stats.worst_time_slot !== stats.best_time_slot && (
            <div className="metric-card metric-card--warn">
              <p className="metric-label">Worst Time Slot</p>
              <p className="metric-value">{stats.worst_time_slot}</p>
            </div>
          )}
        </div>
      )}

      {/* Excuse wall */}
      {stats.top_excuses?.length > 0 && (
        <div className="insights-card">
          <h3 className="insights-card-title">Excuse Wall</h3>
          <ul className="excuse-list">
            {stats.top_excuses.map((ex, i) => (
              <li key={i} className="excuse-item">
                <span className="excuse-rank">#{i + 1}</span>
                <span className="excuse-text">"{ex.reason}"</span>
                <span className="excuse-count">{ex.count}×</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Claude AI analysis */}
      {insights && (
        <div className="ai-analysis">
          <div className="ai-analysis-badge">✦ Claude AI Analysis</div>

          {insights.pattern_summary && (
            <div className="insights-card">
              <h3 className="insights-card-title">What Claude Sees</h3>
              <p className="insights-text">{insights.pattern_summary}</p>
            </div>
          )}

          {(insights.strengths?.length > 0 || insights.weak_spots?.length > 0) && (
            <div className="insights-two-col">
              {insights.strengths?.length > 0 && (
                <div className="insights-card insights-card--green">
                  <h3 className="insights-card-title">✓ Strengths</h3>
                  <ul className="insights-list">
                    {insights.strengths.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
              )}
              {insights.weak_spots?.length > 0 && (
                <div className="insights-card insights-card--red">
                  <h3 className="insights-card-title">⚠ Weak Spots</h3>
                  <ul className="insights-list">
                    {insights.weak_spots.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}

          {insights.suggestions?.length > 0 && (
            <div className="insights-card">
              <h3 className="insights-card-title">Suggestions for Next Week</h3>
              <ul className="insights-list insights-list--suggestions">
                {insights.suggestions.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </div>
          )}

          <div className="adaptive-plan-cta">
            <div>
              <p className="adaptive-plan-title">Ready to level up?</p>
              <p className="adaptive-plan-sub">
                Claude will generate a new schedule using these behavioral insights
              </p>
            </div>
            <button
              className="generate-btn"
              onClick={onAdaptivePlan}
              disabled={adaptiveLoading}
            >
              {adaptiveLoading ? 'Adapting…' : 'Generate Adaptive Plan →'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

// ── Date helpers ──────────────────────────────────────────────────────────────

function getMonday(d) {
  const date = new Date(d)
  const day = date.getDay()
  date.setDate(date.getDate() - day + (day === 0 ? -6 : 1))
  date.setHours(0, 0, 0, 0)
  return date
}

function formatWeek(date) {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function toISODate(date) {
  return date.toISOString().split('T')[0]
}

function fmtGoalDate(g) {
  if (g.week_start) {
    const d = new Date(g.week_start + 'T00:00:00')
    return 'Week of ' + d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }
  return new Date(g.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [goal, setGoal] = useState('')
  const [goalId, setGoalId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [plan, setPlan] = useState(null)
  const [error, setError] = useState(null)
  const [view, setView] = useState('plan')
  const [taskStatuses, setTaskStatuses] = useState({})
  const [insightsData, setInsightsData] = useState(null)
  const [insightsLoading, setInsightsLoading] = useState(false)
  const [insightsError, setInsightsError] = useState(null)
  const [adaptiveLoading, setAdaptiveLoading] = useState(false)

  // Goal history
  const [goals, setGoals] = useState([])
  const [goalItemLoading, setGoalItemLoading] = useState(null)

  // Week date picker (demo mode)
  const [weekStart, setWeekStart] = useState(() => getMonday(new Date()))

  useEffect(() => {
    axios.get('/goals/').then(r => setGoals(r.data.slice().reverse())).catch(() => {})
  }, [])

  const handleStatusChange = useCallback((taskId, newStatus) => {
    setTaskStatuses(prev => ({ ...prev, [taskId]: newStatus }))
  }, [])

  function initStatuses(tasks) {
    const s = {}
    tasks.forEach(t => { s[t.id] = t.status || 'pending' })
    setTaskStatuses(s)
  }

  function prevWeek() {
    setWeekStart(d => new Date(d.getTime() - 7 * 24 * 60 * 60 * 1000))
  }

  function nextWeek() {
    setWeekStart(d => new Date(d.getTime() + 7 * 24 * 60 * 60 * 1000))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!goal.trim()) return
    setLoading(true)
    setError(null)
    setPlan(null)
    setInsightsData(null)
    setTaskStatuses({})
    setView('plan')
    try {
      const { data: goalData } = await axios.post('/goals/', { goal })
      setGoalId(goalData.id)
      const { data: planData } = await axios.post(
        `/goals/${goalData.id}/generate-plan`,
        { week_start: toISODate(weekStart) }
      )
      setPlan(planData)
      initStatuses(planData.tasks)
      setGoals(prev => [goalData, ...prev])
    } catch (err) {
      setError(
        err.response?.data?.detail ||
        'Something went wrong. Make sure the backend is running and ANTHROPIC_API_KEY is set.'
      )
    } finally {
      setLoading(false)
    }
  }

  async function loadGoal(goalObj) {
    setGoalItemLoading(goalObj.id)
    try {
      const { data: tasks } = await axios.get(`/tasks/?goal_id=${goalObj.id}`)
      setGoalId(goalObj.id)
      setGoal(goalObj.goal)
      if (goalObj.week_start) setWeekStart(new Date(goalObj.week_start + 'T00:00:00'))
      setPlan({ goal_id: goalObj.id, summary: goalObj.goal, tasks })
      initStatuses(tasks)
      setInsightsData(null)
      setInsightsError(null)
      setView('plan')
    } catch {
      // silently fail — stays on home
    } finally {
      setGoalItemLoading(null)
    }
  }

  async function handleGetInsights() {
    setInsightsLoading(true)
    setInsightsError(null)
    try {
      const { data } = await axios.post('/insights/generate')
      setInsightsData(data)
      setView('insights')
    } catch (err) {
      setInsightsError(err.response?.data?.detail || 'Failed to generate insights.')
    } finally {
      setInsightsLoading(false)
    }
  }

  async function handleAdaptivePlan() {
    if (!goalId) return
    setAdaptiveLoading(true)
    setInsightsError(null)
    try {
      const { data: planData } = await axios.post(
        `/goals/${goalId}/generate-adaptive-plan`,
        { week_start: toISODate(weekStart) }
      )
      setPlan(planData)
      initStatuses(planData.tasks)
      setInsightsData(null)
      setView('plan')
    } catch (err) {
      setInsightsError(err.response?.data?.detail || 'Failed to generate adaptive plan.')
    } finally {
      setAdaptiveLoading(false)
    }
  }

  function handleStartOver() {
    setPlan(null)
    setGoal('')
    setGoalId(null)
    setInsightsData(null)
    setTaskStatuses({})
    setError(null)
    setInsightsError(null)
    setWeekStart(getMonday(new Date()))
    setView('plan')
  }

  const totalTasks = plan ? plan.tasks.length : 0
  const doneTasks = Object.values(taskStatuses).filter(s => s === 'done').length
  const actedTasks = doneTasks + Object.values(taskStatuses).filter(s => s === 'skipped').length
  const progressPct = totalTasks > 0 ? (doneTasks / totalTasks) * 100 : 0

  const tasksByDay = plan
    ? DAYS.reduce((acc, day) => {
        acc[day] = plan.tasks.filter(t =>
          t.scheduled_time.toLowerCase().startsWith(day.toLowerCase()) ||
          t.scheduled_time.toLowerCase().startsWith(day.slice(0, 3).toLowerCase())
        )
        return acc
      }, {})
    : {}

  const isLoading = loading || insightsLoading || adaptiveLoading
  const loadingText = loading ? 'Claude is crafting your plan…'
    : insightsLoading ? 'Analyzing your patterns…'
    : 'Claude is adapting your plan…'

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <PetalIcon />
          <span className="brand-name">PetalPlan</span>
        </div>

        {plan && !isLoading ? (
          <nav className="header-nav">
            <button
              className={`nav-tab ${view === 'plan' ? 'nav-tab--active' : ''}`}
              onClick={() => setView('plan')}
            >
              Plan
            </button>
            <button
              className={`nav-tab ${view === 'insights' ? 'nav-tab--active' : ''}`}
              onClick={() => insightsData ? setView('insights') : handleGetInsights()}
            >
              Insights
            </button>
          </nav>
        ) : (
          <span className="header-tagline">✦ AI-Powered Planning</span>
        )}
      </header>

      <main className="app-main">
        {/* Home */}
        {!plan && !isLoading && (
          <section className="hero">
            <div className="hero-badge">✦ Powered by Claude AI</div>

            <h1>
              Turn your goal into an{' '}
              <span className="accent">adaptive weekly plan</span>
            </h1>

            <p className="hero-sub">
              Describe what you want to achieve and Claude will craft a structured,
              realistic weekly schedule that learns from your habits.
            </p>

            <div className="form-card">
              <form className="goal-form" onSubmit={handleSubmit}>
                <label className="form-label">What's your goal?</label>
                <textarea
                  className="goal-input"
                  placeholder="e.g. Get a software engineering job in 3 months — I need to practice DSA, system design, and build side projects"
                  value={goal}
                  onChange={e => setGoal(e.target.value)}
                  rows={4}
                />

                {/* Week picker */}
                <div className="week-picker-row">
                  <span className="week-picker-label">Schedule for</span>
                  <div className="week-picker">
                    <button type="button" className="week-nav-btn" onClick={prevWeek}>‹</button>
                    <span className="week-display">Week of {formatWeek(weekStart)}</span>
                    <button type="button" className="week-nav-btn" onClick={nextWeek}>›</button>
                  </div>
                </div>

                <div className="form-footer">
                  <span className="form-hint">Takes ~20–40 seconds</span>
                  <button type="submit" className="generate-btn" disabled={!goal.trim()}>
                    Generate My Plan →
                  </button>
                </div>
              </form>
            </div>

            {error && <p className="error-msg">{error}</p>}

            {/* Goal history */}
            {goals.length > 0 && (
              <div className="prev-goals">
                <span className="section-label">Previous Goals</span>
                <ul className="goals-list">
                  {goals.map(g => (
                    <li key={g.id} className="goal-item">
                      <span className="goal-item-text">{g.goal}</span>
                      <span className="goal-item-meta">{fmtGoalDate(g)}</span>
                      <button
                        className="goal-view-btn"
                        onClick={() => loadGoal(g)}
                        disabled={goalItemLoading === g.id}
                      >
                        {goalItemLoading === g.id ? '…' : 'View →'}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        {/* Loading */}
        {isLoading && <LoadingState text={loadingText} />}

        {/* Plan view */}
        {plan && !isLoading && view === 'plan' && (
          <section className="plan-section">
            <div className="plan-header-band">
              <div className="plan-header-row">
                <div className="plan-header-left">
                  <p className="plan-week">Week of {formatWeek(weekStart)}</p>
                  <h2 className="plan-title">Your Weekly Plan</h2>
                  <p className="plan-summary">{plan.summary}</p>
                </div>
                <div className="plan-header-right">
                  <div className="progress-bar-wrap">
                    <div className="progress-bar">
                      <div className="progress-bar-fill" style={{ width: `${progressPct}%` }} />
                    </div>
                    <span className="progress-label">{doneTasks}/{totalTasks}</span>
                  </div>
                  <div className="plan-btn-row">
                    {actedTasks > 0 && (
                      <button
                        className="insights-btn"
                        onClick={insightsData ? () => setView('insights') : handleGetInsights}
                      >
                        {insightsData ? 'Insights →' : 'Get Insights →'}
                      </button>
                    )}
                    <button className="new-goal-btn" onClick={handleStartOver}>
                      ← New Goal
                    </button>
                  </div>
                </div>
              </div>
              {insightsError && (
                <p className="error-msg" style={{ marginTop: 8 }}>{insightsError}</p>
              )}
            </div>

            <div className="week-scroll">
              <div className="week-grid">
                {DAYS.map(day => (
                  <div key={day} className="day-col">
                    <div className="day-label">{day.slice(0, 3)}</div>
                    {tasksByDay[day]?.length > 0
                      ? tasksByDay[day].map(t => (
                          <TaskCard key={t.id} task={t} onStatusChange={handleStatusChange} />
                        ))
                      : <div className="rest-label">Rest day</div>
                    }
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {/* Insights view */}
        {insightsData && !isLoading && view === 'insights' && (
          <InsightsView
            data={insightsData}
            onAdaptivePlan={handleAdaptivePlan}
            adaptiveLoading={adaptiveLoading}
          />
        )}
      </main>
    </div>
  )
}
