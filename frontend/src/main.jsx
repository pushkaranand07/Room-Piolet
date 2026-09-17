import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowUp, CalendarDays, Check, Clock3, Compass, RotateCcw, Sparkles, Users, Video, X } from "lucide-react";
import "./styles.css";

const suggestions = [
  { icon: CalendarDays, label: "Plan a team meeting", text: "Book a meeting room tomorrow from 10:00 AM to 12:00 PM for 6 people with a projector. My name is Alex." },
  { icon: Video, label: "Find a video room", text: "Find a room on 25 September 2026 from 2:00 PM to 3:30 PM for 8 people with video conferencing. My name is Alex." },
  { icon: Clock3, label: "Check availability", text: "Find an available room today from 4:00 PM for 1 hour for 4 people. No special equipment is required. My name is Alex." },
];

const HISTORY_KEY = "roompilot.history.v1";
const PAYLOAD_KEY = "roompilot.payload.v1";
const PAYLOAD_HISTORY_KEY = "roompilot.payload-history.v1";

function formatBookingTime(value) {
  if (!value) return "Scheduled";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function RoomOptions({ data, onAction, interactive }) {
  return <div className="payload-panel room-options"><div className="payload-heading"><strong>{data.rooms.length} room{data.rooms.length === 1 ? "" : "s"} available</strong><span>{interactive ? "Select a room to continue" : "Previous room search"}</span></div><div className="room-grid">{data.rooms.map((room) => <button className="room-card" type="button" disabled={!interactive} key={room.id} onClick={() => onAction(room.name)}><div className="room-card-top"><strong>{room.name}</strong><span><Users size={13} /> {room.capacity}</span></div><div className="room-equipment">{(room.equipments || []).map((equipment) => <span key={equipment}>{equipment}</span>)}</div><span className="room-card-action">{interactive ? "Choose room" : "Room option"} <ArrowUp size={14} /></span></button>)}</div></div>;
}

function BookingCard({ data, kind }) {
  const booking = data.booking || {};
  const title = kind === "booking_receipt" ? "Booking confirmed" : kind === "cancellation_receipt" ? "Booking cancelled" : kind === "booking_detail" ? "Booking details" : "Your bookings";
  const bookings = kind === "booking_list" ? data.bookings || [] : [booking];
  return <div className={`payload-panel booking-panel ${kind}`}><div className="payload-heading"><strong>{title}</strong><span>{bookings.length} booking{bookings.length === 1 ? "" : "s"}</span></div>{bookings.length === 0 ? <p className="payload-empty">No active bookings found.</p> : bookings.map((item, index) => <div className="booking-item" key={item.booking_id || index}><div><span className="booking-label">{item.booking_id || "Reservation"}</span><strong>{item.room_name || item.room_id || "Meeting room"}</strong></div><div className="booking-meta"><span><CalendarDays size={13} /> {formatBookingTime(item.start_time)}</span>{item.booked_by && <span><Users size={13} /> {item.booked_by}</span>}</div></div>)}</div>;
}

function PayloadRenderer({ payload, onAction, interactive = true }) {
  if (!payload?.type) return null;
  if (payload.type === "room_options") return <RoomOptions data={payload} onAction={onAction} interactive={interactive} />;
  if (["booking_receipt", "cancellation_receipt", "booking_list", "booking_detail"].includes(payload.type)) return <BookingCard data={payload} kind={payload.type} />;
  if (payload.type === "confirmation") return <div className="payload-panel confirmation-panel"><div className="payload-heading"><strong>Ready to book?</strong><span>{interactive ? "Review the details above, then confirm." : "Previous confirmation"}</span></div>{interactive && <><button className="payload-action" type="button" onClick={() => onAction("yes")}><Check size={16} /> Confirm booking</button><button className="payload-secondary" type="button" onClick={() => onAction("no")}><X size={16} /> Cancel</button></>}</div>;
  return null;
}

function DateClarification({ onSubmit }) {
  const [date, setDate] = useState("");
  return <div className="date-clarification"><label htmlFor="booking-date">Choose a date</label><div className="date-clarification-row"><input id="booking-date" type="date" value={date} onChange={(event) => setDate(event.target.value)} /><button type="button" className="payload-action" disabled={!date} onClick={() => onSubmit(date)}><CalendarDays size={15} /> Use date</button></div></div>;
}

function ErrorNotice({ message, onRetry }) {
  return <div className="error-message"><X size={14} /> <span>{message}</span>{onRetry && <button type="button" onClick={onRetry}>Retry</button>}</div>;
}

function App() {
  const [messages, setMessages] = useState(() => { try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch { return []; } });
  const [payload, setPayload] = useState(() => { try { return JSON.parse(localStorage.getItem(PAYLOAD_KEY) || "null"); } catch { return null; } });
  const [payloadHistory, setPayloadHistory] = useState(() => { try { return JSON.parse(localStorage.getItem(PAYLOAD_HISTORY_KEY) || "[]"); } catch { return []; } });
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [lastRequest, setLastRequest] = useState("");
  const endRef = useRef(null);

  useEffect(() => { fetch("/api/booking").then((response) => response.json()).then((data) => { setMessages(data.messages || []); setPayload(data.ui || null); }).catch(() => {}); }, []);
  useEffect(() => { localStorage.setItem(HISTORY_KEY, JSON.stringify(messages)); }, [messages]);
  useEffect(() => { if (payload) localStorage.setItem(PAYLOAD_KEY, JSON.stringify(payload)); else localStorage.removeItem(PAYLOAD_KEY); }, [payload]);
  useEffect(() => { localStorage.setItem(PAYLOAD_HISTORY_KEY, JSON.stringify(payloadHistory)); }, [payloadHistory]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, sending]);

  async function submitRequest(event, actionText) {
    event?.preventDefault();
    const request = (actionText || input).trim();
    if (!request || sending) return;
    setLastRequest(request);
    setSending(true);
    setError("");
    setInput("");
    try {
      const response = await fetch("/api/booking", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_input: request }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The request could not be completed.");
      setMessages(data.messages || []);
      setPayload(data.ui || null);
      if (data.ui) setPayloadHistory((history) => [...history, { messageCount: data.messages?.length || 0, payload: data.ui }]);
    } catch (requestError) {
      setError(requestError.message);
      setInput(request);
    } finally {
      setSending(false);
    }
  }

  function resetConversation() {
    localStorage.removeItem(HISTORY_KEY);
    localStorage.removeItem(PAYLOAD_KEY);
    localStorage.removeItem(PAYLOAD_HISTORY_KEY);
    window.location.href = "/reset";
  }

  return (
    <div className="app-background">
      <div className="app-frame">
        <aside className="sidebar">
          <div className="brand"><span className="brand-symbol">R</span><span>RoomPilot</span></div>
          <div className="sidebar-content">
            <span className="overline">MEETING OPERATIONS</span>
            <h1>Rooms that keep work moving.</h1>
            <p>Find a space that fits your people, timing, and setup in one natural conversation.</p>
            <div className="sidebar-rule" />
            <div className="sidebar-item"><Check size={15} /><span>Availability-aware search</span></div>
            <div className="sidebar-item"><Check size={15} /><span>Equipment matched automatically</span></div>
            <div className="sidebar-item"><Check size={15} /><span>Fast reservation workflow</span></div>
          </div>
          <div className="sidebar-footer"><span className="live-dot" /> Local workspace <span className="footer-separator">/</span> Secure session</div>
        </aside>

        <main className="workspace">
          <header className="topbar">
            <div className="assistant-heading"><span className="assistant-mark"><Sparkles size={16} /></span><div><strong>RoomPilot assistant</strong><span><i className="live-dot" /> Online and ready</span></div></div>
            <button className="icon-button" onClick={resetConversation} title="Start a new conversation" aria-label="Start a new conversation"><RotateCcw size={18} /></button>
          </header>
          <div className="context-strip"><Compass size={16} /><span>Give me a date, time, group size, and any equipment you need.</span></div>

          <section className="conversation" aria-live="polite">
            {messages.length === 0 ? <div className="empty-state">
              <div className="empty-icon"><Sparkles size={22} /></div>
              <span className="overline">YOUR CONCIERGE FOR MEETINGS</span>
              <h2>What are you planning?</h2>
              <p>Start with a complete request or choose a quick brief below. I will take it from there.</p>
              <div className="suggestions">{suggestions.map(({ icon: Icon, label, text }) => <button className="suggestion-card" key={label} onClick={() => setInput(text)}><span className="suggestion-icon"><Icon size={17} /></span><span><strong>{label}</strong><small>{text}</small></span><ArrowUp size={16} className="suggestion-arrow" /></button>)}</div>
            </div> : messages.map((message, index) => <div className={`message-row ${message.type === "human" ? "from-user" : "from-assistant"}`} key={`${index}-${message.content}`}>
              <div className={`message-avatar ${message.type === "human" ? "user-avatar" : "assistant-avatar"}`}>{message.type === "human" ? "You" : <Sparkles size={14} />}</div>
              <div className="message-bubble">{message.content}</div>
            </div>)}
            {(payload ? payloadHistory.slice(0, -1) : payloadHistory).map((entry, index) => <PayloadRenderer key={`${entry.messageCount}-${index}`} payload={entry.payload} onAction={() => {}} interactive={false} />)}
            {payload && <PayloadRenderer payload={payload} onAction={(action) => submitRequest(null, action)} />}
            {payload?.type === "clarification" && payload.missing_fields?.includes("start_date") && <DateClarification onSubmit={(date) => submitRequest(null, date)} />}
            {sending && <div className="message-row from-assistant"><div className="message-avatar assistant-avatar"><Sparkles size={14} /></div><div className="message-bubble typing"><span /><span /><span /></div></div>}
            <div ref={endRef} />
          </section>

          <footer className="composer-area">
            {error && <ErrorNotice message={error} onRetry={lastRequest && !sending ? () => submitRequest(null, lastRequest) : null} />}
            <form className="composer" onSubmit={submitRequest}><input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Describe your meeting..." aria-label="Describe your meeting" disabled={sending} /><button className="send-button" type="submit" disabled={!input.trim() || sending} aria-label="Send request"><ArrowUp size={20} /></button></form>
            <div className="composer-meta"><span><Users size={13} /> RoomPilot handles the details</span><span>Press Enter to send</span></div>
          </footer>
        </main>
      </div>
    </div>
  );
}

export default App;

createRoot(document.getElementById("root")).render(<App />);
