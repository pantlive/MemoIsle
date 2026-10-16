package com.memoisle.app.data

import java.nio.ByteBuffer
import java.security.GeneralSecurityException
import java.security.SecureRandom
import java.text.Normalizer
import java.util.Base64
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

class WrongMasterPasswordException : RuntimeException("主密码不正确。")

class VaultDecryptException : RuntimeException("有条目无法解密，可能已损坏或被篡改。")

/** 解锁所需的包裹参数，来自服务器的密码库状态。 */
data class VaultKeyMaterial(
    val kdf: String,
    val iterations: Int,
    val salt: String,
    val wrappedKey: String,
    val wrapIv: String,
)

/**
 * 与 Web 端相同的密码库加密：主密码经 PBKDF2-SHA256 派生包裹密钥，AES-GCM 解开随机库密钥，
 * 每个条目再用库密钥 AES-GCM 加密，附加认证数据绑定条目 ID。主密码和库密钥都不离开本机。
 */
object VaultCrypto {
    const val KDF = "pbkdf2-sha256"
    const val MIN_ITERATIONS = 600_000
    private const val KEY_WRAP_AAD = "memoisle-vault-key:v1"
    private const val ITEM_AAD_PREFIX = "memoisle-vault-item:v1:"
    private const val GCM_TAG_BITS = 128
    private val random = SecureRandom()

    /**
     * 自己实现 PBKDF2：系统自带实现把密码字符转成字节的方式因 Android 版本而异，
     * 这里固定按 NFC 规范化后的 UTF-8 计算，与浏览器的 WebCrypto 结果一致。
     */
    fun deriveWrappingKey(password: String, salt: ByteArray, iterations: Int): ByteArray {
        val passwordBytes = Normalizer.normalize(password, Normalizer.Form.NFC).toByteArray(Charsets.UTF_8)
        val mac = Mac.getInstance("HmacSHA256")
        require(passwordBytes.isNotEmpty()) { "请输入主密码" }
        mac.init(SecretKeySpec(passwordBytes, "HmacSHA256"))
        mac.update(salt)
        mac.update(ByteBuffer.allocate(4).putInt(1).array())
        val block = mac.doFinal()
        val result = block.copyOf()
        val buffer = block.copyOf()
        for (round in 1 until iterations) {
            mac.update(buffer)
            mac.doFinal(buffer, 0)
            for (index in result.indices) {
                result[index] = (result[index].toInt() xor buffer[index].toInt()).toByte()
            }
        }
        passwordBytes.fill(0)
        return result
    }

    fun unlock(password: String, material: VaultKeyMaterial): SecretKey {
        require(password.isNotEmpty()) { "请输入主密码" }
        if (material.kdf != KDF) {
            throw IllegalStateException("不支持的密码库格式，请更新 MemoIsle。")
        }
        val wrappingKey = deriveWrappingKey(password, decode(material.salt), material.iterations)
        return try {
            val raw = gcm(
                Cipher.DECRYPT_MODE,
                wrappingKey,
                decode(material.wrapIv),
                KEY_WRAP_AAD.toByteArray(Charsets.UTF_8),
                decode(material.wrappedKey),
            )
            SecretKeySpec(raw, "AES").also { raw.fill(0) }
        } catch (error: AEADBadTagException) {
            throw WrongMasterPasswordException()
        } finally {
            wrappingKey.fill(0)
        }
    }

    fun encryptItem(key: SecretKey, id: String, plaintext: ByteArray): Pair<String, String> {
        val iv = ByteArray(12).also(random::nextBytes)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(GCM_TAG_BITS, iv))
        cipher.updateAAD(itemAad(id))
        return encode(iv) to encode(cipher.doFinal(plaintext))
    }

    fun decryptItem(key: SecretKey, id: String, iv: String, ciphertext: String): ByteArray {
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(GCM_TAG_BITS, decode(iv)))
            cipher.updateAAD(itemAad(id))
            cipher.doFinal(decode(ciphertext))
        } catch (error: GeneralSecurityException) {
            throw VaultDecryptException()
        } catch (error: IllegalArgumentException) {
            throw VaultDecryptException()
        }
    }

    private fun gcm(mode: Int, key: ByteArray, iv: ByteArray, aad: ByteArray, data: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(mode, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BITS, iv))
        cipher.updateAAD(aad)
        return cipher.doFinal(data)
    }

    private fun itemAad(id: String): ByteArray = "$ITEM_AAD_PREFIX$id".toByteArray(Charsets.UTF_8)

    private fun encode(bytes: ByteArray): String = Base64.getEncoder().encodeToString(bytes)

    private fun decode(text: String): ByteArray = Base64.getDecoder().decode(text)
}
