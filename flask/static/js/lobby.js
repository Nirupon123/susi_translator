
//stored in localStorage so they persist on refresh
let rooms = JSON.parse(localStorage.getItem('susi_rooms') || '[]');

function renderRooms() {
    const grid = document.getElementById('rooms-grid');
    grid.innerHTML = '';

    if (rooms.length === 0) {
        grid.innerHTML = '<p style="color:#999;">No rooms yet. Click "Create Room" to get started</p>';
        return;
    }

    rooms.forEach(room => {
        const card = document.createElement('div');
        card.className = 'room-card';
        card.innerHTML = `
            <h3>${room.name}</h3>
            <p>ID: ${room.tenant_id.slice(0, 8)}...</p>
            <div class="room-card-footer">
                <button class="delete-btn" onclick="deleteRoom(event, '${room.tenant_id}')">Delete</button>
            </div>
        `;
        card.onclick = () => {
            window.location.href = `/config/${room.tenant_id}`;
        };
        grid.appendChild(card);
    });
}

async function createRoom() {
    const name = prompt('Enter a name for this room:');
    if (!name) return;

    // POST /session to get a server-minted tenant_id
    const response = await fetch('/session', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: 'youtube'})
    });

    const data = await response.json();
    const tenant_id = data.tenant_id;

    // store room locally
    rooms.push({name, tenant_id});
    localStorage.setItem('susi_rooms', JSON.stringify(rooms));

    renderRooms();
}

// render on page load
renderRooms();

function deleteRoom(event, tenant_id) {
    event.stopPropagation(); // prevent card click triggering redirect
    rooms = rooms.filter(r => r.tenant_id !== tenant_id);
    localStorage.setItem('susi_rooms', JSON.stringify(rooms));
    renderRooms();
}