import { test } from "node:test";
import assert from "node:assert/strict";
import { makeZip, crc32 } from "../../app/zip.js";
import { python } from "./support.js";

const utf8 = (s) => new TextEncoder().encode(s);

test("CRC-32 matches the standard check value", () => {
  assert.equal(crc32(utf8("123456789")), 0xcbf43926);
  assert.equal(crc32(new Uint8Array(0)), 0);
});

test("Python's zipfile reads the archive, CRCs check out, names are UTF-8", async () => {
  const big = new Uint8Array(200000).map((_, i) => (i * 31) & 0xff);
  const entries = [
    { name: "session.json", data: utf8('{"schema":"tonekit.session.v1"}') },
    { name: "clips/g01-c.wav", data: big },
    { name: "clips/一杯水.wav", data: utf8("x") },
    { name: "clips/empty.wav", data: new Uint8Array(0) },
  ];
  const blob = makeZip(entries, new Date(Date.UTC(2026, 9, 3, 18, 24, 40)));
  assert.equal(blob.type, "application/zip");
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const out = python(
    [
      "import sys, zipfile, json, hashlib",
      "z = zipfile.ZipFile(sys.argv[1])",
      "assert z.testzip() is None",
      "print(json.dumps([[i.filename, i.compress_type, i.file_size, i.date_time,",
      "  hashlib.sha256(z.read(i)).hexdigest()] for i in z.infolist()], ensure_ascii=False))",
    ].join("\n"),
    bytes,
    ".zip",
  );
  const infos = JSON.parse(out);
  const sha = async (d) => Buffer.from(await crypto.subtle.digest("SHA-256", d)).toString("hex");
  assert.deepEqual(infos.map((i) => i[0]), entries.map((e) => e.name));
  for (const [i, info] of infos.entries()) {
    assert.equal(info[1], 0, "stored, no compression");
    assert.equal(info[2], entries[i].data.length);
    assert.deepEqual(info[3], [2026, 10, 3, 18, 24, 40]);
    assert.equal(info[4], await sha(entries[i].data));
  }
});

test("an empty archive is still a valid zip", async () => {
  const bytes = new Uint8Array(await makeZip([]).arrayBuffer());
  const out = python("import sys, zipfile\nprint(len(zipfile.ZipFile(sys.argv[1]).namelist()))", bytes, ".zip");
  assert.equal(out.trim(), "0");
});
