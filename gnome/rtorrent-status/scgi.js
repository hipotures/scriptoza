'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const MODERN_FIELDS = [
    'd.hash=',
    'd.name=',
    'd.state=',
    'd.is_active=',
    'd.complete=',
    'd.hashing=',
    'd.size_bytes=',
    'd.completed_bytes=',
    'd.down.rate=',
    'd.up.rate=',
    'd.message=',
    'd.peers_connected=',
    'd.peers_complete=',
    'd.peers_accounted=',
    'd.up.total=',
    'd.ratio=',
];

const LEGACY_FIELDS = [
    'd.get_hash=',
    'd.get_name=',
    'd.get_state=',
    'd.is_active=',
    'd.get_complete=',
    'd.get_hashing=',
    'd.get_size_bytes=',
    'd.get_completed_bytes=',
    'd.get_down_rate=',
    'd.get_up_rate=',
    'd.get_message=',
    'd.get_peers_connected=',
    'd.get_peers_complete=',
    'd.get_peers_accounted=',
    'd.get_up_total=',
    'd.get_ratio=',
];

const MODES = ['jsonrpc', 'xmlrpc-v2', 'xmlrpc-v1'];
const modeCache = new Map();

class RpcProtocolError extends Error {}

function escapeXml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

function decodeXmlEntities(text) {
    return text.replace(/&(#x[0-9a-fA-F]+|#\d+|amp|lt|gt|quot|apos);/g, (_match, entity) => {
        if (entity === 'amp') return '&';
        if (entity === 'lt') return '<';
        if (entity === 'gt') return '>';
        if (entity === 'quot') return '"';
        if (entity === 'apos') return "'";
        if (entity.startsWith('#x'))
            return String.fromCodePoint(parseInt(entity.slice(2), 16));
        return String.fromCodePoint(parseInt(entity.slice(1), 10));
    });
}

export function buildScgiRequest(bodyText) {
    const encoder = new TextEncoder();
    const body = encoder.encode(typeof bodyText === 'string' ? bodyText : JSON.stringify(bodyText));
    const headers = encoder.encode(`CONTENT_LENGTH\x00${body.length}\x00SCGI\x001\x00`);
    const prefix = encoder.encode(`${headers.length}:`);
    const result = new Uint8Array(prefix.length + headers.length + 1 + body.length);
    result.set(prefix, 0);
    result.set(headers, prefix.length);
    result[prefix.length + headers.length] = 0x2c;
    result.set(body, prefix.length + headers.length + 1);
    return result;
}

export function buildXmlRpcRequest(method, params) {
    const paramsXml = params
        .map(param => `<param><value><string>${escapeXml(param)}</string></value></param>`)
        .join('');
    return `<?xml version="1.0"?><methodCall><methodName>${escapeXml(method)}</methodName><params>${paramsXml}</params></methodCall>`;
}

function splitScgiBody(rawText) {
    const crlfIndex = rawText.indexOf('\r\n\r\n');
    if (crlfIndex !== -1)
        return rawText.slice(crlfIndex + 4);
    const lfIndex = rawText.indexOf('\n\n');
    if (lfIndex !== -1)
        return rawText.slice(lfIndex + 2);
    return rawText;
}

function parseXmlNode(xml, pos) {
    const lt = xml.indexOf('<', pos);
    if (lt === -1)
        return null;
    if (xml.startsWith('<?', lt) || xml.startsWith('<!', lt)) {
        const end = xml.indexOf('>', lt);
        return end === -1 ? null : parseXmlNode(xml, end + 1);
    }
    const gt = xml.indexOf('>', lt);
    if (gt === -1)
        throw new RpcProtocolError('Malformed XML-RPC response');
    const rawTag = xml.slice(lt + 1, gt).trim();
    if (rawTag.startsWith('/'))
        return null;
    const selfClosing = rawTag.endsWith('/');
    const tag = (selfClosing ? rawTag.slice(0, -1) : rawTag).split(/\s+/)[0];
    if (selfClosing)
        return {tag, children: [], text: '', nextPos: gt + 1};

    const children = [];
    let text = '';
    let cursor = gt + 1;
    while (cursor < xml.length) {
        const nextLt = xml.indexOf('<', cursor);
        if (nextLt === -1)
            throw new RpcProtocolError(`Unclosed XML tag <${tag}>`);
        if (nextLt > cursor)
            text += xml.slice(cursor, nextLt);
        if (xml.startsWith(`</${tag}>`, nextLt))
            return {tag, children, text, nextPos: nextLt + tag.length + 3};
        if (xml.startsWith('</', nextLt))
            throw new RpcProtocolError(`Unexpected closing tag inside <${tag}>`);
        const child = parseXmlNode(xml, nextLt);
        if (!child)
            break;
        children.push(child);
        cursor = child.nextPos;
    }
    throw new RpcProtocolError(`Unclosed XML tag <${tag}>`);
}

function decodeXmlValue(valueNode) {
    if (!valueNode)
        return '';
    if (valueNode.children.length === 0)
        return decodeXmlEntities(valueNode.text);
    const inner = valueNode.children[0];
    switch (inner.tag) {
    case 'string':
        return decodeXmlEntities(inner.text);
    case 'int':
    case 'i4':
    case 'i8':
    case 'ex:i8':
    case 'double':
        return Number(inner.text.trim()) || 0;
    case 'boolean':
        return inner.text.trim() === '1' || inner.text.trim().toLowerCase() === 'true';
    case 'array': {
        const dataNode = inner.children.find(c => c.tag === 'data');
        if (!dataNode)
            return [];
        return dataNode.children.filter(c => c.tag === 'value').map(decodeXmlValue);
    }
    case 'struct': {
        const obj = {};
        for (const member of inner.children.filter(c => c.tag === 'member')) {
            const nameNode = member.children.find(c => c.tag === 'name');
            const valNode = member.children.find(c => c.tag === 'value');
            if (nameNode)
                obj[decodeXmlEntities(nameNode.text.trim())] = decodeXmlValue(valNode);
        }
        return obj;
    }
    default:
        return decodeXmlEntities(inner.text);
    }
}

export function parseXmlRpcResponse(rawText) {
    const bodyText = splitScgiBody(rawText).trim();
    const root = parseXmlNode(bodyText, 0);
    if (!root || root.tag !== 'methodResponse')
        throw new RpcProtocolError('Invalid XML-RPC response');
    const faultNode = root.children.find(c => c.tag === 'fault');
    if (faultNode) {
        const fault = decodeXmlValue(faultNode.children.find(c => c.tag === 'value'));
        throw new RpcProtocolError(fault?.faultString || `XML-RPC fault ${fault?.faultCode ?? ''}`.trim());
    }
    const paramsNode = root.children.find(c => c.tag === 'params');
    const paramNode = paramsNode?.children.find(c => c.tag === 'param');
    const valueNode = paramNode?.children.find(c => c.tag === 'value');
    const result = decodeXmlValue(valueNode);
    if (!Array.isArray(result))
        throw new RpcProtocolError('Unexpected XML-RPC multicall result');
    return result;
}

export function parseScgiResponse(rawText) {
    const bodyText = splitScgiBody(rawText);
    let parsed;
    try {
        parsed = JSON.parse(bodyText);
    } catch (error) {
        throw new RpcProtocolError(`Invalid JSON-RPC response: ${error.message}`);
    }
    if (parsed.error)
        throw new RpcProtocolError(parsed.error.message || JSON.stringify(parsed.error));
    if (!Array.isArray(parsed.result))
        throw new RpcProtocolError('Unexpected rTorrent JSON-RPC response');
    return parsed.result;
}

function connectAsync(client, host, port, cancellable) {
    return new Promise((resolve, reject) => {
        client.connect_to_host_async(host, port, cancellable, (source, res) => {
            try {
                resolve(source.connect_to_host_finish(res));
            } catch (error) {
                reject(error);
            }
        });
    });
}

function writeAllAsync(stream, bytes, cancellable) {
    return new Promise((resolve, reject) => {
        stream.write_all_async(bytes, GLib.PRIORITY_DEFAULT, cancellable, (source, res) => {
            try {
                const [ok] = source.write_all_finish(res);
                resolve(ok);
            } catch (error) {
                reject(error);
            }
        });
    });
}

function readBytesAsync(stream, count, cancellable) {
    return new Promise((resolve, reject) => {
        stream.read_bytes_async(count, GLib.PRIORITY_DEFAULT, cancellable, (source, res) => {
            try {
                resolve(source.read_bytes_finish(res));
            } catch (error) {
                reject(error);
            }
        });
    });
}

async function sendScgi({host, port, bodyText, timeoutSeconds = 3}) {
    const client = new Gio.SocketClient();
    const cancellable = new Gio.Cancellable();
    let timedOut = false;
    const timeoutId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, timeoutSeconds, () => {
        timedOut = true;
        cancellable.cancel();
        return GLib.SOURCE_REMOVE;
    });
    let connection = null;
    try {
        connection = await connectAsync(client, host, port, cancellable);
        await writeAllAsync(connection.get_output_stream(), buildScgiRequest(bodyText), cancellable);
        const input = connection.get_input_stream();
        const chunks = [];
        let totalLength = 0;
        while (true) {
            const bytes = await readBytesAsync(input, 65536, cancellable);
            const size = bytes.get_size();
            if (size === 0)
                break;
            const data = bytes.toArray();
            chunks.push(data);
            totalLength += data.length;
        }
        const merged = new Uint8Array(totalLength);
        let offset = 0;
        for (const chunk of chunks) {
            merged.set(chunk, offset);
            offset += chunk.length;
        }
        return new TextDecoder().decode(merged);
    } catch (error) {
        if (timedOut)
            throw new Error(`Timed out connecting to ${host}:${port}`);
        throw error;
    } finally {
        GLib.Source.remove(timeoutId);
        try { connection?.close(null); } catch {}
    }
}

async function queryWithMode({host, port, mode, timeoutSeconds}) {
    if (mode === 'jsonrpc') {
        const raw = await sendScgi({
            host,
            port,
            bodyText: JSON.stringify({
                jsonrpc: '2.0',
                id: 1,
                method: 'd.multicall2',
                params: ['', 'main', ...MODERN_FIELDS],
            }),
            timeoutSeconds,
        });
        return parseScgiResponse(raw);
    }
    if (mode === 'xmlrpc-v2') {
        const raw = await sendScgi({
            host,
            port,
            bodyText: buildXmlRpcRequest('d.multicall2', ['', 'main', ...MODERN_FIELDS]),
            timeoutSeconds,
        });
        return parseXmlRpcResponse(raw);
    }
    const raw = await sendScgi({
        host,
        port,
        bodyText: buildXmlRpcRequest('d.multicall', ['main', ...LEGACY_FIELDS]),
        timeoutSeconds,
    });
    return parseXmlRpcResponse(raw);
}

export async function fetchTorrents({host, port, timeoutSeconds = 3}) {
    const key = `${host}:${port}`;
    const cached = modeCache.get(key);
    const candidates = cached ? [cached, ...MODES.filter(m => m !== cached)] : MODES;
    let lastProtocolError = null;
    for (const mode of candidates) {
        try {
            const result = await queryWithMode({host, port, mode, timeoutSeconds});
            modeCache.set(key, mode);
            return result;
        } catch (error) {
            if (!(error instanceof RpcProtocolError))
                throw error;
            modeCache.delete(key);
            lastProtocolError = error;
        }
    }
    throw lastProtocolError ?? new Error(`Unsupported rTorrent RPC on ${key}`);
}
