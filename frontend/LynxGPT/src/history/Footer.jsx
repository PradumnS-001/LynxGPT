import pfp1 from '../assets/pfp1.png';

function Footer() {
    const handleRefreshColors = () => {
        try {
            const root = document.documentElement;

            // Simple random hue rotation for accent color
            const hue = Math.floor(Math.random() * 360);

            // Create a vibrant accent based on random hue
            const accent = `hsl(${hue}, 90%, 55%)`;
            const dark = `hsl(${hue}, 80%, 10%)`;

            root.style.setProperty("--accent-vibrant", accent);
            root.style.setProperty("--accent-dark", dark);
            root.style.setProperty("--accent-border", accent);
            root.style.setProperty("--accent-glow", accent);

            // If you have an --accent-rgb variable used elsewhere, approximate it
            // by converting the HSL to RGB via a tiny canvas or a quick approximation.
            // Here we'll just clear it so fallbacks use --accent-vibrant.
        } catch {
            // fail silently
        }
    };

    return (
        <div className="Footer">
            <div
            style={{ display:'flex',flexDirection:'row', paddingLeft:'8px' }}>
                <img src={pfp1} alt="pfp" style={{ maxHeight:'32px', borderRadius:'50%', marginTop:'2px'}}/>
                <p style={{ lineHeight:'14px',
                        paddingTop: '6px'}}>
                    <span style={{
                        fontWeight: '200',
                        fontSize: '1rem',
                        fontFamily: 'sans-serif',
                        paddingLeft: '8px',
                    }}>
                        The Gru
                    </span>
                    <br />
                    <span style={{
                        fontWeight: '50',
                        fontSize: '0.5rem',
                        fontFamily: 'sans-serif',
                        paddingLeft: '8px',
                        color: 'gray',
                        paddingTop: '0px'
                    }}>
                        One and Only
                    </span></p>
            </div>
        </div>
    )
}

export default Footer;