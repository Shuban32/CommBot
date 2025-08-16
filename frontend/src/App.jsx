// frontend/src/App.jsx
import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

const API_BASE_URL = 'http://localhost:8000';
console.log("API Base URL (Runtime):", API_BASE_URL);

function App() {
  // Remove state for direct text input if not needed anymore
  // const [inputText, setInputText] = useState('Rohit Sharma hits a massive six over long on!');
  const [processedCommentary, setProcessedCommentary] = useState(''); // For LLM output
  const [rawCommentary, setRawCommentary] = useState(''); // For scraped text
  const [audioUrl, setAudioUrl] = useState(null);
  const [isLoading, setIsLoading] = useState(false); // General loading for commentary generation
  const [error, setError] = useState(null);
  const [matchesLoading, setMatchesLoading] = useState(false);
  const [liveMatches, setLiveMatches] = useState([]);
  const [pastMatches, setPastMatches] = useState([]);
  const [selectedMatchUrl, setSelectedMatchUrl] = useState(''); // Track selected match
  const audioRef = useRef(null);

  // Fetch matches on component mount (no change)
  useEffect(() => {
    const fetchMatches = async () => {
      setMatchesLoading(true);
      setError(null);
      try {
        console.log(`Fetching live matches from ${API_BASE_URL}/live_matches`);
        const liveRes = await axios.get(`${API_BASE_URL}/live_matches`);
        setLiveMatches(liveRes.data.matches || []);
        console.log(`Fetching past matches from ${API_BASE_URL}/past_matches`);
        const pastRes = await axios.get(`${API_BASE_URL}/past_matches`);
        setPastMatches(pastRes.data.matches || []);
      } catch (err) {
        console.error("Error fetching matches:", err);
        let errorMsg = `Failed to fetch matches. Is the backend running?`;
        if (err.response) { errorMsg += ` Status: ${err.response.status} - ${err.response.data?.detail || err.message}`; }
        else { errorMsg += ` Error: ${err.message}`; }
        setError(errorMsg);
        setLiveMatches([]); setPastMatches([]);
      } finally {
        setMatchesLoading(false);
      }
    };
    fetchMatches();
  }, []);

   // Effect to play audio when audioUrl changes (no change)
  useEffect(() => {
    if (audioUrl && audioRef.current) {
      console.log("Attempting to play audio:", audioUrl);
      audioRef.current.load();
      audioRef.current.play().catch(e => console.warn("Audio autoplay prevented by browser:", e));
    }
  }, [audioUrl]);

  // --- NEW Handler for clicking a match URL ---
  const handleMatchClick = async (matchUrl) => {
      if (!matchUrl || isLoading) return;
      console.log("Match clicked, requesting commentary for:", matchUrl);
      setIsLoading(true);
      setError(null);
      setRawCommentary('');
      setProcessedCommentary('');
      setAudioUrl(null);
      setSelectedMatchUrl(matchUrl); // Highlight selected match visually (optional)

      try {
          const response = await axios.post(`${API_BASE_URL}/scrape_commentary`, {
              url: matchUrl,
          });
          console.log("Scrape & Generate response:", response.data);
          setRawCommentary(response.data.raw_commentary || '(Raw commentary not available)');
          setProcessedCommentary(response.data.processed_commentary || '(Processed commentary not available)');

          if (response.data.audio_url) {
              const fullAudioUrl = `${API_BASE_URL}${response.data.audio_url}`;
              setAudioUrl(fullAudioUrl);
          } else {
              setAudioUrl(null);
          }

      } catch (err) {
          console.error("Error scraping/generating commentary:", err);
          let errorMsg = `Failed to get commentary for ${matchUrl.split('/').pop()}.`;
          if (err.response) { errorMsg += ` Status: ${err.response.status} - ${err.response.data?.detail || err.message}`; }
          else { errorMsg += ` Error: ${err.message}`; }
          setError(errorMsg);
          setRawCommentary('');
          setProcessedCommentary('');
          setAudioUrl(null);
      } finally {
          setIsLoading(false);
      }
  };


  // --- Keep handleFeedback (no change needed initially) ---
  const handleFeedback = async (score) => {
     // Use processedCommentary for feedback text
     const commentaryToSubmit = processedCommentary || rawCommentary;
     if (!commentaryToSubmit || commentaryToSubmit.startsWith("(")) return;
     console.log(`Submitting feedback: Score ${score} for commentary: ${commentaryToSubmit.substring(0, 50)}...`);
     try {
       await axios.post(`${API_BASE_URL}/feedback`, {
         commentary_text: commentaryToSubmit, // Send processed or raw text
         score: score,
         comment: `Score ${score} submitted from frontend.`
       });
       alert("Feedback submitted successfully!");
     } catch (err) {
        console.error("Error submitting feedback:", err);
        let errorMsg = `Failed to submit feedback.`;
        if (err.response) { errorMsg += ` Status: ${err.response.status} - ${err.response.data?.detail || err.message}`; }
        else { errorMsg += ` Error: ${err.message}`; }
        setError(errorMsg);
     }
  };

  // --- Render Logic ---
  return (
    <div className="App" style={{ padding: '20px', fontFamily: 'sans-serif' }}>
      <h1>AI Cricket Commentary Generator</h1>

      {/* Remove or repurpose the direct text input section if desired */}
      {/* <div style={{ marginBottom: '20px', border: '1px solid #eee', padding: '15px', borderRadius: '5px' }}> ... </div> */}

      {/* Display Area for Loading/Errors */}
      {isLoading && <p style={{ color: 'blue' }}>Loading commentary for {selectedMatchUrl.split('/').pop()}...</p>}
      {matchesLoading && <p style={{ color: 'blue' }}>Loading match lists...</p>}
      {error && <p style={{ color: 'red', fontWeight: 'bold', marginTop: '15px' }}>Error: {error}</p>}


      {/* Display Generated Commentary and Audio */}
      {/* Show results only when not loading and commentary exists */}
      {!isLoading && (processedCommentary || rawCommentary) && (
        <div style={{ marginTop: '20px', border: '1px solid #ccc', padding: '15px', borderRadius: '5px' }}>
          <h2>Commentary for: {selectedMatchUrl.split('/').pop()}</h2>
          {rawCommentary && <p><strong>Latest Raw:</strong> {rawCommentary}</p>}
          {processedCommentary && <p><strong>Processed:</strong> <span style={{ fontStyle: 'italic' }}>"{processedCommentary}"</span></p>}

          {audioUrl && (
            <div style={{marginTop: '10px'}}>
               <audio ref={audioRef} controls src={audioUrl} style={{ width: '100%' }}>
                 Your browser does not support the audio element. Direct link: <a href={audioUrl} target="_blank" rel="noopener noreferrer">Download Audio</a>
               </audio>
            </div>
          )}
          {/* Feedback Buttons - enable only if processed commentary is valid */}
           {processedCommentary && !processedCommentary.startsWith("(") && (
             <div style={{marginTop: '15px', paddingTop: '10px', borderTop: '1px solid #eee'}}>
                Rate this commentary:
                <button onClick={() => handleFeedback(1)} style={{marginLeft: '10px'}}>1 Poor</button>
                <button onClick={() => handleFeedback(3)} style={{marginLeft: '10px'}}>3 Okay</button>
                <button onClick={() => handleFeedback(5)} style={{marginLeft: '10px'}}>5 Great</button>
             </div>
           )}
        </div>
      )}

      {/* Display Match Lists - Make items clickable */}
      <div style={{ marginTop: '30px', display: 'flex', justifyContent: 'space-around', flexWrap: 'wrap' }}>
         <div style={{ flexBasis: '45%', marginBottom: '20px'}}>
            <h2>Live / Upcoming Matches</h2>
            {liveMatches.length > 0 ? (
               <ul style={{ listStyle: 'none', padding: 0 }}>{liveMatches.map((url, i) =>
                  <li key={`live-${i}`} style={{ marginBottom: '5px' }}>
                    {/* Use button or styled link for click handling */}
                    <button onClick={() => handleMatchClick(url)} disabled={isLoading} style={{ background: 'none', border: 'none', padding: '0', color: 'blue', textDecoration: 'underline', cursor: 'pointer' }}>
                        {url.split('/').slice(-2).join('/')}
                    </button>
                  </li>)}
               </ul>
            ) : <p>{matchesLoading ? 'Loading...' : 'No live/upcoming matches found.'}</p>}
         </div>
         <div style={{ flexBasis: '45%', marginBottom: '20px'}}>
            <h2>Past Matches (Recent)</h2>
            {pastMatches.length > 0 ? (
               <ul style={{ listStyle: 'none', padding: 0 }}>{pastMatches.slice(0, 15).map((url, i) =>
                  <li key={`past-${i}`} style={{ marginBottom: '5px' }}>
                     <button onClick={() => handleMatchClick(url)} disabled={isLoading} style={{ background: 'none', border: 'none', padding: '0', color: 'blue', textDecoration: 'underline', cursor: 'pointer' }}>
                        {url.split('/').slice(-2).join('/')}
                     </button>
                  </li>)}
               </ul>
            ) : <p>{matchesLoading ? 'Loading...' : 'No past matches found.'}</p>}
         </div>
      </div>
    </div>
  );
}

export default App;